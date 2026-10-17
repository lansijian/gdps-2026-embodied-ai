"""Phase 4.4.1 compatibility regressions. All fixture data is SYNTHETIC_TEST."""
import argparse
import math
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/g1'))
from field_evidence import EvidenceCollector, add_capture_arguments
from field_gates_centering import analyze


def image(t=10., depth=False):
    arr=(np.ones((48,64),dtype=np.float32)*.8 if depth else np.arange(48*64*3,dtype=np.uint8).reshape(48,64,3))
    return SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=int(t),nanosec=round((t-int(t))*1e9)),
        frame_id='camera'),width=64,height=48,encoding='32FC1' if depth else 'rgb8',array=arr)


def camera_info(t=1.):
    return SimpleNamespace(header=image(t).header,width=64,height=48,
        k=[50.,0.,32.,0.,50.,24.,0.,0.,1.],d=[],r=np.eye(3).ravel().tolist(),
        p=[50.,0.,32.,0.,0.,50.,24.,0.,0.,0.,1.,0.])


@pytest.fixture
def collector(tmp_path,monkeypatch):
    class Bridge:
        def imgmsg_to_cv2(self,msg,desired_encoding):
            assert desired_encoding in ('rgb8','passthrough')
            return msg.array.copy()
    monkeypatch.setitem(sys.modules,'cv_bridge',SimpleNamespace(CvBridge=Bridge))
    monkeypatch.setitem(sys.modules,'tf2_ros',None)
    monkeypatch.setitem(sys.modules,'message_filters',None)
    p=argparse.ArgumentParser();add_capture_arguments(p)
    args=p.parse_args(['--out-dir',str(tmp_path/'capture'),'--rgb-topic','/rgb',
        '--depth-topic','/depth','--camera-info-topic','/info'])
    return EvidenceCollector(args,'SYNTHETIC_TEST')


def evidence(c):
    return {'data_source':'SYNTHETIC_TEST','rows':c.rows,'time_reference':10.}


def assert_raw_saved(c,msg):
    assert len(c.rows['frames'])==1,c.errors
    row=c.rows['frames'][0]
    np.testing.assert_array_equal(np.load(c.root/row['rgb_raw_file']),msg.array)
    assert (c.root/row['rgb_raw_png']).is_file()
    assert row['rgb_stamp_sec']==10.
    assert (row['width'],row['height'])==(64,48)
    assert not row['rgbd_synchronized']
    return row


def test_rgb_without_depth_exports_original_and_timestamps(collector):
    msg=image();collector.ingest('/rgb',msg,10000000001)
    row=assert_raw_saved(collector,msg)
    assert row['depth_file'] is None and row['depth_stamp_sec'] is None
    assert row['bag_stamps_ns']['/rgb']==10000000001
    a=analyze(evidence(collector),collector.root,'A')
    assert a['status']=='OK' and a['rgb_status']=='RGB_RAW_OK'
    assert a['valid_rgb_frames']==1 and a['rgbd_status']=='UNKNOWN'
    assert not a['field_verified'] and not a['live_motion']


@pytest.mark.parametrize('info_first',[True,False])
def test_unsynchronized_info_keeps_original_and_only_2d(collector,info_first):
    msg=image()
    if info_first: collector.ingest('/info',camera_info(1.))
    collector.ingest('/rgb',msg)
    if not info_first: collector.ingest('/info',camera_info(1.))
    row=assert_raw_saved(collector,msg)
    assert row['camera_info_valid_2d'] and not row['camera_info_time_matched']
    assert row['camera_info_stamp_sec']==1.
    with patch('field_gates_centering.target_pixel',return_value=(42.,24.)):
        c=analyze(evidence(collector),collector.root,'C')
        m=c['measurements'][0]
        assert c['status']=='OK' and m['pixel_2d_status']=='OK'
        assert m['pixel_du']==10.
        assert m['localization_3d_status']=='UNKNOWN'
        assert not m['range']['valid']
        assert m['range']['p_camera'] is None and m['range']['p_base'] is None
        assert c['depth_repeatability']['n']==0
        d=analyze(evidence(collector),collector.root,'D')
        assert d['status']=='UNKNOWN'
        assert 'plan' not in d['measurements'][0]


def test_mismatched_depth_headers_do_not_upgrade_raw_rgb(collector):
    collector.rgbd(image(),image(10.2,depth=True),camera_info(10.))
    row=assert_raw_saved(collector,image())
    assert row['rgbd_error']=='header_stamp_mismatch'
    assert row['depth_file'] is None
    with patch('field_gates_centering.target_pixel',return_value=(42.,24.)):
        assert analyze(evidence(collector),collector.root,'D')['status']=='UNKNOWN'


def test_raw_pointcloud_health_survives_missing_scan_and_odom(collector,monkeypatch):
    points=[(1.,0.,.3),(0.,2.,.3),(-3.,0.,.3),(0.,-4.,.3)]
    monkeypatch.setitem(sys.modules,'sensor_msgs_py',SimpleNamespace(point_cloud2=SimpleNamespace(read_points=lambda *a,**k:points)))
    pc=SimpleNamespace(header=SimpleNamespace(stamp=image().header.stamp,frame_id='livox_frame'),width=4,height=1)
    collector.ingest(collector.args.pc_topic,pc)
    b=analyze(evidence(collector),collector.root,'B')
    assert b['status']=='OK' and b['LIDAR_RAW_OK']
    assert b['lidar_raw_status']=='LIDAR_RAW_OK'
    assert b['streams']['pc']['status']=='OK'
    assert b['scan_status']=='UNKNOWN' and b['odom_status']=='UNKNOWN'
    assert not b['all_streams_ok'] and not b['body_directions_calibrated']
    sample=b['streams']['pc']['samples'][0]
    assert sample['frame_id']=='livox_frame'
    assert [sample[k+'_m'] for k in ('front','left','back','right')]==[1,2,3,4]


def test_every_gate_keeps_motion_disabled_for_rgb_only(collector):
    collector.ingest('/info',camera_info())
    collector.ingest('/rgb',image())
    for gate in 'ABCDE':
        result=analyze(evidence(collector),collector.root,gate)
        assert not result['live_motion']
        assert not result['field_verified']
        for m in result.get('measurements',[]):
            assert not m.get('plan',{}).get('execute_allowed',False)

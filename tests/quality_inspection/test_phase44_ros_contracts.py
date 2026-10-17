"""Actual ROS API smoke contracts; synthetic messages, never field verification."""
import numpy as np
import pytest
rclpy = pytest.importorskip('rclpy', reason='G1 Foxy required; Windows cannot verify ROS runtime')
from sensor_msgs.msg import Image, CameraInfo
from geometry_msgs.msg import TransformStamped
from rclpy.time import Time
from tf2_ros import Buffer
from cv_bridge import CvBridge
from image_geometry import PinholeCameraModel
from message_filters import SimpleFilter, ApproximateTimeSynchronizer


def test_installed_foxy_sync_bridge_model_tf_contracts(tmp_path):
    rclpy.init()
    try:
        bridge=CvBridge()
        msg=bridge.cv2_to_imgmsg(np.zeros((48,64,3),dtype=np.uint8),encoding='rgb8')
        msg.header.stamp.sec=10
        depth=bridge.cv2_to_imgmsg(np.ones((48,64),dtype=np.float32),encoding='32FC1')
        depth.header.stamp.sec=10;depth.header.stamp.nanosec=10000000
        info=CameraInfo();info.width=64;info.height=48
        info.k=[50.,0.,32.,0.,50.,24.,0.,0.,1.]
        info.r=[1.,0.,0.,0.,1.,0.,0.,0.,1.]
        info.p=[50.,0.,32.,0.,0.,50.,24.,0.,0.,0.,1.,0.]
        info.header.stamp.sec=10
        # Exercise the real collector, not only library constructors, when run on G1 Foxy.
        import argparse
        import sys
        from pathlib import Path
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/g1'))
        from field_evidence import EvidenceCollector, add_capture_arguments
        from field_gates_centering import analyze
        p=argparse.ArgumentParser();add_capture_arguments(p)
        args=p.parse_args(['--out-dir',str(tmp_path/'capture'),'--rgb-topic','/rgb',
                          '--depth-topic','/depth','--camera-info-topic','/info'])
        collector=EvidenceCollector(args,'SYNTHETIC_TEST')
        msg.header.frame_id=depth.header.frame_id=info.header.frame_id='camera'
        collector.ingest('/rgb',msg)
        assert len(collector.rows['frames'])==1
        raw=collector.rows['frames'][0]['rgb_raw_file']
        assert (collector.root/raw).is_file()
        info.header.stamp.sec=1
        collector.ingest('/info',info)
        collector.ingest('/depth',depth)
        row=collector.rows['frames'][0]
        assert row['camera_info_valid_2d'] and not row['rgbd_synchronized']
        info.header.stamp.sec=10
        collector.ingest('/info',info)
        assert len(collector.rows['frames'])==1 and row['rgbd_synchronized']
        assert not row['depth_aligned_to_rgb']  # Registration has not been verified.
        result=analyze({'data_source':'SYNTHETIC_TEST','rows':collector.rows},collector.root,'A')
        assert result['rgb_status']=='RGB_RAW_OK' and result['rgbd_status']=='UNKNOWN'
        assert not result['live_motion'] and not result['field_verified']
        fs=[SimpleFilter() for _ in range(3)]
        sync=ApproximateTimeSynchronizer(fs,8,.05)
        received=[];sync.registerCallback(lambda *ms:received.append(ms))
        for f,m in zip(fs,[msg,depth,info]):f.signalMessage(m)
        assert len(received)==1
        assert bridge.imgmsg_to_cv2(depth,'passthrough').shape==(48,64)
        model=PinholeCameraModel();model.fromCameraInfo(info)
        assert model.projectPixelTo3dRay((32.,24.))==pytest.approx((0,0,1))
        rect=np.empty((48,64,3),dtype=np.uint8)
        model.rectifyImage(bridge.imgmsg_to_cv2(msg,'rgb8'),rect)
        buf=Buffer()
        tr=TransformStamped();tr.header.frame_id='base';tr.child_frame_id='camera'
        tr.transform.rotation.w=1.;tr.transform.translation.x=.2
        buf.set_transform_static(tr,'SYNTHETIC_TEST')
        result=buf.lookup_transform('base','camera',Time(seconds=10))
        assert result.transform.translation.x==pytest.approx(.2)
    finally:
        rclpy.shutdown()

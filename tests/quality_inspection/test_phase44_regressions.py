from __future__ import annotations
import math
import sys
from dataclasses import replace, asdict
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pytest
from gdps_qi.adapters.camera import CameraFrame, CameraInfo
from gdps_qi.perception.camera_geometry import (ProjectionStatus, optical_to_base_rotation,
    make_t_base_camera, project_base_point_to_pixel, choose_lateral_direction_by_reprojection, se2_apply_y)
from gdps_qi.perception.rgbd_target_geometry import assess_rgbd_sync, estimate_target_range
from gdps_qi.validation.sensor_validation_report import assess_lidar_depth_agreement
from gdps_qi.centering.target_centering_controller import TargetCenteringController, CenteringMode, CenteringConfig
from gdps_qi.perception.detection_types import Detection
from gdps_qi.transforms.transform_manager import TransformManager

INFO = CameraInfo(640,480,500,500,320,240)


def frame(t=1.0):
    return CameraFrame(np.zeros((480,640,3),dtype=np.uint8),np.ones((480,640),dtype=np.float32)*0.8,
        t,INFO,rgb_stamp_sec=t,depth_stamp_sec=t+.01,camera_info_stamp_sec=t,
        intrinsics_trusted=True,depth_scale_confirmed=True,depth_aligned_to_rgb=True)


def controller():
    tf = TransformManager()
    tf.set_transform('robot_center','camera_color_optical_frame',make_t_base_camera(),1,'synthetic',static=True)
    return TargetCenteringController(tf)


def det(u=320, target='one'):
    return Detection(target,'tablet',0.9,(0,0,10,10),(u,240.))


def test_optical_basis_and_principal_point():
    r=optical_to_base_rotation()
    np.testing.assert_array_equal(r@[0,0,1],[1,0,0])
    np.testing.assert_array_equal(r@[1,0,0],[0,-1,0])
    np.testing.assert_array_equal(r@[0,1,0],[0,0,-1])
    assert np.linalg.det(r)==1
    p=project_base_point_to_pixel((2,0,0),make_t_base_camera(),INFO)
    assert p.status==ProjectionStatus.OK
    assert (p.u,p.v,p.du,p.dv)==(320,240,0,0)


@pytest.mark.parametrize('optical_x',[-.2,.2])
def test_left_right_pixel_sign(optical_x):
    t=make_t_base_camera()
    p=t@np.array([optical_x,0,1,1])
    result=project_base_point_to_pixel(tuple(p[:3]),t,INFO)
    assert np.sign(result.du)==np.sign(optical_x)


@pytest.mark.parametrize('yaw',[-.5,0,.5])
@pytest.mark.parametrize('pitch',[-.3,.3])
@pytest.mark.parametrize('x',[-.18,.18])
def test_reprojection_for_rotated_translated_camera(yaw,pitch,x):
    cz,sz,cy,sy=math.cos(yaw),math.sin(yaw),math.cos(pitch),math.sin(pitch)
    rz=np.array([[cz,-sz,0],[sz,cz,0],[0,0,1]])
    ry=np.array([[cy,0,sy],[0,1,0],[-sy,0,cy]])
    t=make_t_base_camera((.15,-.08,.6),rz@ry@optical_to_base_rotation())
    p=(t@np.array([x,0,1.2,1]))[:3]
    lat,before,after=choose_lateral_direction_by_reprojection(p,t,INFO)
    assert abs(before)>50
    assert lat in ('left','right')
    assert abs(after)<abs(before)-5
    dy=.05 if lat=='left' else -.05
    actual=project_base_point_to_pixel(p,se2_apply_y(dy,t),INFO)
    assert actual.du==pytest.approx(after)


def test_bearing_sign_can_be_wrong():
    # Camera points left of robot: target has positive base bearing yet lies right of optical axis.
    yaw=.7
    r=np.array([[math.cos(yaw),-math.sin(yaw),0],[math.sin(yaw),math.cos(yaw),0],[0,0,1]])
    t=make_t_base_camera(rotation_base_from_optical=r@optical_to_base_rotation())
    p=(t@np.array([.2,0,1,1]))[:3]
    assert p[1]>0
    lat,before,after=choose_lateral_direction_by_reprojection(p,t,INFO)
    assert lat=='right'
    assert abs(after)<abs(before)


def test_behind_and_nonfinite_reject_not_centered():
    p=project_base_point_to_pixel((-1,0,0),make_t_base_camera(),INFO)
    assert p.status==ProjectionStatus.INVALID_TARGET_BEHIND_CAMERA
    assert math.isnan(p.du)
    assert choose_lateral_direction_by_reprojection((-1,0,0),make_t_base_camera(),INFO)[0]=='none'
    assert project_base_point_to_pixel((math.nan,0,0),make_t_base_camera(),INFO).status==ProjectionStatus.INVALID_DEGENERATE


@pytest.mark.parametrize('field,value', [('depth_stamp_sec',None),('rgb_stamp_sec',None),
    ('camera_info_stamp_sec',None),('depth_stamp_sec',1.2),('camera_info_stamp_sec',1.2),
    ('depth_stamp_sec',math.nan),('depth_aligned_to_rgb',False),('depth_scale_confirmed',False)])
def test_sync_fails_closed(field,value):
    f=replace(frame(),**{field:value})
    assert not assess_rgbd_sync(f).ok
    assert not estimate_target_range(f,320,240).valid


def test_sync_real_independent_delta_and_resolution():
    f=frame()
    assert assess_rgbd_sync(f).ok
    assert assess_rgbd_sync(f).delta_rgb_depth_s==pytest.approx(.01)
    assert not assess_rgbd_sync(replace(f,depth_m=np.ones((10,10)))).ok
    assert not estimate_target_range(f,-10,240).valid
    assert not estimate_target_range(replace(f,info=replace(INFO,distortion=(.1,0,0,0,0))),320,240).valid


@pytest.mark.parametrize('bad_index',range(4))
def test_equal_ranges_cannot_bypass_correspondence(bad_index):
    flags=[True]*4;flags[bad_index]=False
    r=assess_lidar_depth_agreement(.8,.8,*flags)
    assert not r.fusion_allowed
    assert not r.compare_allowed


def test_fusion_remains_disabled_and_nonfinite_rejected():
    assert assess_lidar_depth_agreement(.8,.8,True,True,True,True).compare_allowed
    assert not assess_lidar_depth_agreement(.8,.8,True,True,True,True).fusion_allowed
    assert not assess_lidar_depth_agreement(math.nan,.8,True,True,True,True).compare_allowed


def test_observations_are_not_robot_movements_and_wrong_direction_holds():
    c=controller()
    for t in range(1,5):
        r=c.step(frame(t),det(420))
        assert r.motion_steps==0
        assert r.observe_frames==t
    r=c.step(frame(5),det(430),moved_since_last=True)
    assert not r.safe and r.motion_steps==1
    assert 'error_increased_after_motion' in r.reasons
    assert not c.step(frame(6),det(320)).safe


def test_same_target_fresh_frames_and_workspace_required():
    c=controller()
    for t in range(1,4): r=c.step(frame(t),det())
    assert r.centered
    assert r.mode==CenteringMode.OBSERVE_ONLY
    assert 'centered_but_workspace_not_ready' in r.reasons
    assert not c.step(frame(4),det(target='two')).safe
    c.reset()
    assert c.step(frame(10),det()).safe
    assert not c.step(frame(10),det()).safe


def test_target_loss_timeout_and_motion_budget():
    c=controller()
    assert not c.step(frame(),None).safe
    c.reset()
    with patch('gdps_qi.centering.target_centering_controller.time.monotonic',return_value=c._t0_mono+121):
        assert 'timeout' in c.step(frame(),det()).reasons
    c.reset();c.cfg.max_motion_steps=1
    c.step(frame(),det(420))
    assert not c.step(frame(2),det(410),moved_since_last=True).safe


sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/g1'))
from field_evidence import sectors, series_stats
from field_gates_centering import analyze


def test_four_sector_valid_returns_and_sensor_timing():
    s=sectors([1,2,3,4,math.nan,math.inf],[0,math.pi/2,math.pi,-math.pi/2,0,0])
    assert [s[k+'_m'] for k in ('front','left','back','right')]==[1,2,3,4]
    assert s['valid_points']==4
    assert sectors([],[])['front_m'] is None
    assert series_stats([{'stamp':1},{'stamp':1.1},{'stamp':1.2}])['hz']==pytest.approx(10)
    assert series_stats([{'stamp':2},{'stamp':1}])['non_monotonic']==1


def test_empty_evidence_independent_unknown(tmp_path):
    for source in ('REAL_SENSOR','RECORDED_REPLAY','SYNTHETIC_TEST'):
        for gate in 'ABCDE':
            r=analyze({'data_source':source,'rows':{}},tmp_path,gate)
            assert r['status']=='UNKNOWN'
            assert not r['field_verified']
            assert not r['live_motion']


def test_saved_depth_frame_analysis_and_missing_intrinsics(tmp_path):
    f=frame()
    np.save(tmp_path/'rgb.npy',f.rgb);np.save(tmp_path/'depth.npy',f.depth_m)
    row={k:getattr(f,k) for k in ('stamp','rgb_stamp_sec','depth_stamp_sec','camera_info_stamp_sec',
        'rgb_frame_id','depth_frame_id','intrinsics_trusted','depth_scale_confirmed','depth_aligned_to_rgb')}
    row.update(info=asdict(INFO),rgb_file='rgb.npy',depth_file='depth.npy',tf=make_t_base_camera().tolist())
    e={'data_source':'SYNTHETIC_TEST','rows':{'frames':[row]}}
    assert analyze(e,tmp_path,'A')['valid_frames']==1
    with patch('field_gates_centering.target_pixel',return_value=(420,240)):
        d=analyze(e,tmp_path,'D')
        assert d['measurements'][0]['plan']['recommended_lateral']=='right'
        assert not d['measurements'][0]['plan']['execute_allowed']
        row['intrinsics_trusted']=False
        assert analyze(e,tmp_path,'C')['measurements'][0]['status']=='UNKNOWN'
    assert not d['field_verified']


def test_all_external_booleans_cannot_authorize_grasp():
    from gdps_qi.centering.manipulation_ready import ManipulationReadyGate
    from gdps_qi.transforms.frame_registry import FrameGraphReport
    c=controller()
    for t in range(1,4): result=c.step(frame(t),det(),workspace_ok=True)
    assert result.centered
    estimate=estimate_target_range(frame(3),320,240,make_t_base_camera())
    report=FrameGraphReport(base_frame='robot_center',T_base_camera=make_t_base_camera().tolist(),
                            T_base_target=np.eye(4).tolist())
    out=ManipulationReadyGate().evaluate(result,estimate,report,True,True,True,
        calibration_id='pretend',calibration_verified=True,tcp_verified=True,depth_reliable=True,tf_fresh=True)
    assert not out.manipulation_ready
    assert 'source_evidence_bundle_missing' in out.reasons
    assert 'tf_timestamp_evidence_missing_or_stale' in out.reasons


def test_odom_comparison_in_robot_axes_for_rotated_robot():
    from field_evidence import odom_delta
    yaw=math.pi/2
    a={'x':0,'y':0,'frame_id':'odom','orientation_xyzw':[0,0,math.sin(yaw/2),math.cos(yaw/2)]}
    b={**a,'x':-.05,'y':0}
    d=odom_delta(a,b)
    assert d['lateral_left_m']==pytest.approx(.05)
    assert d['forward_m']==pytest.approx(0,abs=1e-10)


def test_stale_tf_and_missing_camera_info_stay_unknown(tmp_path):
    e={'data_source':'RECORDED_REPLAY','tf_lookups':[{'parent':'base','child':'camera','ok':True,'stale':True,'stamp':1,'age_s':10}],'rows':{}}
    r=analyze(e,tmp_path,'E')
    assert r['status']=='UNKNOWN' and len(r['stale'])==1
    f=frame();np.save(tmp_path/'rgb.npy',f.rgb);np.save(tmp_path/'depth.npy',f.depth_m)
    row={k:getattr(f,k) for k in ('stamp','rgb_stamp_sec','depth_stamp_sec','camera_info_stamp_sec',
        'rgb_frame_id','depth_frame_id','intrinsics_trusted','depth_scale_confirmed','depth_aligned_to_rgb')}
    row.update(info=None,rgb_file='rgb.npy',depth_file='depth.npy')
    r=analyze({'data_source':'RECORDED_REPLAY','rows':{'frames':[row]}},tmp_path,'C')
    assert r['status']=='UNKNOWN'
    assert r['measurements'][0]['reason']=='camera_info_missing_or_untrusted'


def test_closed_loop_converges_with_bounded_test_budget():
    from gdps_qi.centering.lateral_closed_loop import LateralClosedLoopSimulator, LateralLoopConfig
    from shared.navigation.factory import build_navigator
    nav=build_navigator();nav.safety.require_heartbeat=False
    try:
        sim=LateralClosedLoopSimulator(nav,(1,.25,.5),make_t_base_camera(),INFO,
            LateralLoopConfig(max_iterations=20))
        centered,history=sim.run()
        assert centered
        assert 2 <= len(history) <= 20
        assert abs(history[0].pixel_du)==pytest.approx(125)
        assert abs(history[-1].pixel_du_after) < 15
        assert abs(history[0].pixel_du)-abs(history[-1].pixel_du_after) > 100
        for row in history:
            assert abs(row.pixel_du_after) < abs(row.pixel_du)
            assert row.pixel_u-INFO.cx==pytest.approx(row.pixel_du)
    finally:
        nav.adapter.close()


def test_foxy_unit_ray_uses_axial_depth_not_unit_distance():
    ray=np.array([.2,0,1.]);ray/=np.linalg.norm(ray)
    est=estimate_target_range(frame(),420,240,make_t_base_camera(),camera_ray=tuple(ray))
    assert est.valid
    assert est.p_camera==pytest.approx((.16,0,.8))
    assert not estimate_target_range(frame(),420,240,camera_ray=(1,0,-1)).valid

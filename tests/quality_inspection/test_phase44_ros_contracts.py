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


def test_installed_foxy_sync_bridge_model_tf_contracts():
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

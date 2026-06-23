
对准下降
{
  "hold_updates_required": 8,
  "lost_timeout_s": 1.0,
  "max_retries": 1,
  "max_updates": 300,
  "finish_altitude_m": 1.2,
  "config": {
    "kp_vx": 0.4,
    "kp_vy": 0.4,
    "max_vx_mps": 0.15,
    "max_vy_mps": 0.15,
    "descend_speed_mps": 0.06,
    "max_ex_cam": 0.07,
    "max_ey_cam": 0.07,
    "deadband_ex_cam": 0.025,
    "deadband_ey_cam": 0.025,
    "min_altitude_m": 1,
    "require_target_locked": true
  }
}

{
  "detection_source": "scene",
  "class_names": [
    "bucket"
  ],
  "min_confidence": 0.35,
  "camera": {
    "fov_x_deg": 76,
    "fov_y_deg": 61,
    "image_x_sign": 1,
    "image_y_sign": -1
  }
}
如果后面发现定位出来的坐标“距离中心偏差被放大”，说明 FOV 设大了，往 72 / 58 调。
如果坐标偏差被压小，实际桶在图像边缘但算出来离中心不够远，说明 FOV 设小了，往 80 / 64 调。
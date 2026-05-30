
gz sim -v4 -r iris_runway.sdf

sim_vehicle.py -D -v ArduCopter -f JSON --add-param-file=$HOME/gz_ws/src/ardupilot_gazebo/config/gazebo-iris-gimbal.parm --console

gz topic -t /world/iris_runway/model/iris_with_gimbal/model/gimbal/link/pitch_link/sensor/camera/image/enable_streaming -m gz.msgs.Boolean -p "data: 1"


conda activate yolo

DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus python3 ~/uav_project/uav_system-rk3588/yolo_app/main.py

cd ~/uav_project/src/
python3 -m app.main 



ffplay -f v4l2 -input_format yuyv422 -video_size 640x480 -framerate 30 /dev/video0

ffplay -fflags nobuffer -flags low_delay -framedrop -sync ext /dev/video0

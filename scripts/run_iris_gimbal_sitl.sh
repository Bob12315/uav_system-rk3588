#!/usr/bin/env bash
set -euo pipefail

GCS_HOST="${GCS_HOST:-10.31.18.108}"
VIDEO_HOST="${VIDEO_HOST:-${GCS_HOST}}"
MAVLINK_PORT="${MAVLINK_PORT:-14550}"
VIDEO_PORT="${VIDEO_PORT:-5600}"
ARDUPILOT_DIR="${ARDUPILOT_DIR:-${HOME}/ardupilot}"
GZ_PARAM_FILE="${GZ_PARAM_FILE:-${HOME}/gz_ws/src/ardupilot_gazebo/config/gazebo-iris-gimbal.parm}"
GZ_WORLD="${GZ_WORLD:-iris_runway.sdf}"
CAMERA_STREAM_TOPIC="${CAMERA_STREAM_TOPIC:-/world/iris_runway/model/iris_with_gimbal/model/gimbal/link/pitch_link/sensor/camera/image/enable_streaming}"
CAMERA_STREAM_DELAY="${CAMERA_STREAM_DELAY:-10}"
TERMINAL_HOLD="${TERMINAL_HOLD:-1}"

run_shell='
set -euo pipefail
title="$1"
shift
printf "\033]0;%s\007" "$title"
echo "== ${title} =="
echo "$*"
echo
"$@"
if [ "${TERMINAL_HOLD:-1}" = "1" ]; then
  echo
  echo "Process exited. Press Enter to close this terminal."
  read -r _
fi
'

open_terminal() {
  local title="$1"
  shift

  if command -v gnome-terminal >/dev/null 2>&1; then
    gnome-terminal --title="${title}" -- bash -lc "${run_shell}" _ "${title}" "$@"
  elif command -v konsole >/dev/null 2>&1; then
    konsole --new-tab --title "${title}" -e bash -lc "${run_shell}" _ "${title}" "$@"
  elif command -v xfce4-terminal >/dev/null 2>&1; then
    xfce4-terminal --title="${title}" --command="$(printf '%q ' bash -lc "${run_shell}" _ "${title}" "$@")"
  elif command -v xterm >/dev/null 2>&1; then
    xterm -T "${title}" -e bash -lc "${run_shell}" _ "${title}" "$@" &
  else
    echo "No supported terminal emulator found." >&2
    echo "Install gnome-terminal, konsole, xfce4-terminal, or xterm." >&2
    exit 1
  fi
}

open_terminal "gz sim iris runway" \
  gz sim -v4 -r "${GZ_WORLD}"

open_terminal "ArduCopter SITL" \
  bash -lc "cd '${ARDUPILOT_DIR}' && ./Tools/autotest/sim_vehicle.py -D -v ArduCopter -f JSON --add-param-file='${GZ_PARAM_FILE}' --console --out=udp:${GCS_HOST}:${MAVLINK_PORT}"

open_terminal "Gimbal camera RTP relay" \
  bash -lc "echo 'Waiting ${CAMERA_STREAM_DELAY}s for Gazebo to start...' && sleep '${CAMERA_STREAM_DELAY}' && gz topic -t '${CAMERA_STREAM_TOPIC}' -m gz.msgs.Boolean -p 'data: 1' && gst-launch-1.0 -v udpsrc port=${VIDEO_PORT} caps='application/x-rtp,media=video,encoding-name=H264,payload=96' ! rtph264depay ! h264parse ! rtph264pay config-interval=1 pt=96 ! udpsink host=${VIDEO_HOST} port=${VIDEO_PORT}"

echo "Started Gazebo, ArduCopter SITL, and camera RTP relay terminals."
echo "  MAVLink out: udp:${GCS_HOST}:${MAVLINK_PORT}"
echo "  Video out:   udp:${VIDEO_HOST}:${VIDEO_PORT}"

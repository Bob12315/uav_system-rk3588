#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

CONTROL_ENV="${CONTROL_ENV:-app}"
YOLO_ENV="${YOLO_ENV:-yolo}"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda was not found." >&2
  exit 1
fi

echo "Checking control environment '${CONTROL_ENV}'..."
conda run -n "${CONTROL_ENV}" bash -lc "cd '${REPO_ROOT}' && python -m app.main --help >/dev/null"
conda run -n "${CONTROL_ENV}" bash -lc "cd '${REPO_ROOT}' && python -m telemetry_link.main --help >/dev/null"
conda run -n "${CONTROL_ENV}" bash -lc "cd '${REPO_ROOT}' && python -m app.main --no-yolo-udp --run-seconds 1 --send-commands false --no-ui --blackbox-enabled false >/dev/null"

echo "Checking YOLO environment '${YOLO_ENV}'..."
conda run -n "${YOLO_ENV}" bash -lc "cd '${REPO_ROOT}/yolo_app' && python main.py --help >/dev/null"
conda run -n "${YOLO_ENV}" python - <<'PY'
import cv2
from rknnlite.api import RKNNLite

print("opencv", cv2.__version__)
print("rknnlite", RKNNLite)
PY

echo
echo "Smoke tests passed."

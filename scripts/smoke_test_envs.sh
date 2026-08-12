#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

CONTROL_ENV="${CONTROL_ENV:-uav-app}"
YOLO_ENV="${YOLO_ENV:-uav-rk3588-yolo}"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda was not found." >&2
  exit 1
fi

echo "Checking control environment '${CONTROL_ENV}'..."
conda run -n "${CONTROL_ENV}" bash -lc "cd '${REPO_ROOT}' && bash scripts/healthcheck/check_app.sh"
conda run -n "${CONTROL_ENV}" bash -lc "cd '${REPO_ROOT}' && python -m app.main --no-yolo-udp --run-seconds 1 --send-commands false --no-ui --blackbox-enabled false >/dev/null"

if [[ "${SKIP_RK3588_YOLO:-false}" == true ]]; then
  echo "Skipping optional RK3588 YOLO smoke test."
  exit 0
fi

[[ "$(uname -m)" == aarch64 || "$(uname -m)" == arm64 ]] || { echo "RK3588 YOLO smoke test requires ARM64; set SKIP_RK3588_YOLO=true for generic hosts." >&2; exit 1; }
echo "Checking RK3588 YOLO environment '${YOLO_ENV}'..."
conda run -n "${YOLO_ENV}" bash -lc "cd '${REPO_ROOT}' && python -m yolo_app.main --help >/dev/null"
conda run -n "${YOLO_ENV}" python - <<'PY'
import cv2
from rknnlite.api import RKNNLite

print("opencv", cv2.__version__)
print("rknnlite", RKNNLite)
PY

echo
echo "Smoke tests passed."

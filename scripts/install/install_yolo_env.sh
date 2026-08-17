#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
YOLO_ENV_NAME="${YOLO_ENV_NAME:-uav-rk3588-yolo}"

die() { echo "ERROR [rk3588-yolo]: $*" >&2; exit 1; }
[[ "$(uname -s)" == Linux ]] || die "requires Linux; detected $(uname -s)"
case "$(uname -m)" in aarch64|arm64) ;; *) die "requires aarch64/arm64 RK3588; detected $(uname -m)";; esac
command -v conda >/dev/null || die "conda is required; install Conda, then rerun scripts/install/install_yolo_env.sh"

compatible="$(tr -d '\0' </proc/device-tree/compatible 2>/dev/null || true)"
if ! printf '%s' "${compatible}" | grep -qi 'rk3588'; then
  die "requires RK3588 board identity in /proc/device-tree/compatible; ARM64 alone is not sufficient"
fi
[[ -e /dev/rknpu || -e /dev/rknpu0 || -d /sys/kernel/debug/rknpu ]] || die "requires RKNN NPU device/driver; check the RK3588 image and driver"

cd "${REPO_ROOT}"
if conda env list | awk '{print $1}' | grep -Fxq "${YOLO_ENV_NAME}"; then
  conda env update -n "${YOLO_ENV_NAME}" -f environment-rk3588-yolo.yml --prune
else
  conda env create -n "${YOLO_ENV_NAME}" -f environment-rk3588-yolo.yml
fi
conda run -n "${YOLO_ENV_NAME}" bash -lc "cd '${REPO_ROOT}' && python -c 'import cv2; from rknnlite.api import RKNNLite; print(cv2.__version__, RKNNLite)'"
test -f "${REPO_ROOT}/data/models/cuadc2026-fp16.rknn" || die "missing deployment model data/models/cuadc2026-fp16.rknn"

echo "RK3588 YOLO environment '${YOLO_ENV_NAME}' is ready."

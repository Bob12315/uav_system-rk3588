#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

YOLO_ENV_NAME="${YOLO_ENV_NAME:-yolo}"
YOLO_PYTHON_VERSION="${YOLO_PYTHON_VERSION:-3.10}"
TUNA_PYPI_INDEX="${TUNA_PYPI_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This RK3588 installer supports Linux only." >&2
  exit 1
fi

case "$(uname -m)" in
  aarch64|arm64) ;;
  *)
    echo "This RK3588 installer requires aarch64/arm64. Detected: $(uname -m)" >&2
    exit 1
    ;;
esac

if [[ "${CONDA_DEFAULT_ENV:-}" != "${YOLO_ENV_NAME}" ]]; then
  echo "Activate conda env '${YOLO_ENV_NAME}' first." >&2
  exit 1
fi

actual_python="$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "${actual_python}" != "${YOLO_PYTHON_VERSION}" ]]; then
  echo "Python ${YOLO_PYTHON_VERSION}.x is required. Current: ${actual_python}" >&2
  exit 1
fi

python -m pip install -i "${TUNA_PYPI_INDEX}" --upgrade pip
python -m pip install -i "${TUNA_PYPI_INDEX}" -r "${REPO_ROOT}/requirements-yolo.txt"

python - <<'PY'
import cv2
import numpy
import yaml
from rknnlite.api import RKNNLite

print("YOLO environment import check passed")
print("opencv", cv2.__version__)
print("numpy", numpy.__version__)
print("rknnlite", RKNNLite)
PY

test -f "${REPO_ROOT}/data/models/best-int8-rk3588.rknn"
echo "YOLO environment '${YOLO_ENV_NAME}' is ready for RK3588."

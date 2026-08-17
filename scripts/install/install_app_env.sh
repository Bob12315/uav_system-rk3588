#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
APP_ENV_NAME="${APP_ENV_NAME:-uav-app}"
APP_PYTHON_VERSION="${APP_PYTHON_VERSION:-3.10}"

die() { echo "ERROR [app environment]: $*" >&2; exit 1; }

[[ "$(uname -s)" == Linux ]] || die "supported component=app requires Linux; detected $(uname -s)"
case "$(uname -m)" in x86_64|amd64|aarch64|arm64) ;; *) die "supported component=app requires x86_64/amd64/aarch64/arm64; detected $(uname -m)";; esac
command -v conda >/dev/null || die "conda is required; install Conda, then rerun scripts/install/install_app_env.sh"

cd "${REPO_ROOT}"
if conda env list | awk '{print $1}' | grep -Fxq "${APP_ENV_NAME}"; then
  conda env update -n "${APP_ENV_NAME}" -f environment-app.yml --prune
else
  conda env create -n "${APP_ENV_NAME}" -f environment-app.yml
fi

conda run -n "${APP_ENV_NAME}" python - <<PY
import sys
assert sys.version_info[:2] == tuple(map(int, "${APP_PYTHON_VERSION}".split("."))), sys.version
PY
conda run -n "${APP_ENV_NAME}" bash -lc "cd '${REPO_ROOT}' && bash scripts/healthcheck/check_app.sh"

echo "App environment '${APP_ENV_NAME}' ready on $(uname -m). RKNN/YOLO is intentionally not installed."

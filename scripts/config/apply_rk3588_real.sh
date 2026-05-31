#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PROFILE_DIR="${REPO_ROOT}/config/profiles/rk3588-real"

python - "${REPO_ROOT}/config/app.yaml" <<'PY'
from pathlib import Path
import sys

import yaml

data = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
if data.get("executor", {}).get("send_commands") is not False:
    raise SystemExit("Refusing profile switch: config/app.yaml executor.send_commands must be false")
PY

cp "${PROFILE_DIR}/telemetry.yaml" "${REPO_ROOT}/config/telemetry.yaml"
cp "${PROFILE_DIR}/yolo.yaml" "${REPO_ROOT}/config/yolo.yaml"

echo "Applied RK3588 real profile."
echo "  telemetry: real eth udpin 0.0.0.0:15001"
echo "  video:     /dev/video41"
echo "Review config/yolo.yaml if the camera device path differs on this board."

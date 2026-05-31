#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
APP_PYTHON="${APP_PYTHON:-${HOME}/anaconda3/envs/app/bin/python}"
YOLO_PYTHON="${YOLO_PYTHON:-${HOME}/anaconda3/envs/yolo/bin/python}"
CONFIG_PYTHON="${APP_PYTHON}"
FAILURES=0
WARNINGS=0

ok() {
  echo "OK:   $*"
}

warn() {
  WARNINGS=$((WARNINGS + 1))
  echo "WARN: $*"
}

fail() {
  FAILURES=$((FAILURES + 1))
  echo "FAIL: $*"
}

check_file() {
  if [[ -f "$1" ]]; then
    ok "$1"
  else
    fail "missing file: $1"
  fi
}

echo "RK3588 UAV health check"
echo "Repository: ${REPO_ROOT}"
echo

if [[ "$(uname -s)" == "Linux" ]]; then
  ok "operating system is Linux"
else
  fail "operating system must be Linux: $(uname -s)"
fi

case "$(uname -m)" in
  aarch64|arm64) ok "architecture is $(uname -m)" ;;
  *) fail "architecture must be aarch64/arm64: $(uname -m)" ;;
esac

check_file "${REPO_ROOT}/config/app.yaml"
check_file "${REPO_ROOT}/config/telemetry.yaml"
check_file "${REPO_ROOT}/config/yolo.yaml"
check_file "${REPO_ROOT}/data/models/best-int8-rk3588.rknn"

echo
if [[ -x "${APP_PYTHON}" ]]; then
  if "${APP_PYTHON}" -c "import fastapi, httpx, numpy, pymavlink, uvicorn, yaml" >/dev/null 2>&1; then
    ok "app environment imports"
  else
    fail "app environment imports failed: ${APP_PYTHON}"
  fi
else
  fail "app Python is missing: ${APP_PYTHON}"
fi

if [[ -x "${YOLO_PYTHON}" ]]; then
  if "${YOLO_PYTHON}" -c "import cv2, numpy, yaml; from rknnlite.api import RKNNLite" >/dev/null 2>&1; then
    ok "YOLO environment imports"
  else
    fail "YOLO environment imports failed: ${YOLO_PYTHON}"
  fi
else
  fail "YOLO Python is missing: ${YOLO_PYTHON}"
fi

echo
if [[ ! -x "${CONFIG_PYTHON}" ]]; then
  CONFIG_PYTHON="$(command -v python3 || command -v python)"
fi
if ! config_summary="$("${CONFIG_PYTHON}" - "${REPO_ROOT}" 2>&1 <<'PY'
from pathlib import Path
import sys

import yaml

root = Path(sys.argv[1])
app = yaml.safe_load((root / "config/app.yaml").read_text(encoding="utf-8")) or {}
telemetry = yaml.safe_load((root / "config/telemetry.yaml").read_text(encoding="utf-8")) or {}
yolo = yaml.safe_load((root / "config/yolo.yaml").read_text(encoding="utf-8")) or {}

send_commands = app.get("executor", {}).get("send_commands")
if send_commands is not False:
    raise SystemExit("executor.send_commands must be false before deployment checks")

data_source = str(telemetry.get("data_source", ""))
active_source = str(telemetry.get("active_source", ""))
if data_source not in {"real", "sitl", "dual"}:
    raise SystemExit(f"invalid telemetry data_source: {data_source}")
if active_source not in {"real", "sitl"}:
    raise SystemExit(f"invalid telemetry active_source: {active_source}")

print(f"send_commands={str(send_commands).lower()}")
print(f"data_source={data_source}")
print(f"active_source={active_source}")
print(f"video_source={yolo.get('source', '')}")
PY
)"; then
  fail "configuration validation failed: ${config_summary}"
  config_summary=""
else
  ok "configuration safety validation"
  printf '%s\n' "${config_summary}" | sed 's/^/     /'
fi

video_source="$(printf '%s\n' "${config_summary}" | sed -n 's/^video_source=//p')"
if [[ "${video_source}" == /dev/* ]]; then
  if [[ -e "${video_source}" ]]; then
    ok "video device exists: ${video_source}"
  else
    warn "video device is not present: ${video_source}"
  fi
elif [[ "${video_source}" =~ ^[0-9]+$ ]]; then
  ok "video source uses UDP port ${video_source}"
else
  warn "video source requires manual verification: ${video_source:-<empty>}"
fi

echo
if command -v ss >/dev/null 2>&1; then
  for port in 5005 5006 8080 8081; do
    if ss -lntu | awk '{print $5}' | grep -Eq "(^|:)${port}$"; then
      ok "port ${port} is listening"
    else
      warn "port ${port} is not listening"
    fi
  done
else
  warn "ss command is unavailable; skipped port checks"
fi

echo
if command -v systemctl >/dev/null 2>&1; then
  for service in uav-app.service uav-yolo.service; do
    if systemctl --user cat "${service}" >/dev/null 2>&1; then
      ok "installed user service: ${service}"
      if systemctl --user is-active --quiet "${service}"; then
        ok "active user service: ${service}"
      else
        warn "inactive user service: ${service}"
      fi
    else
      warn "user service is not installed: ${service}"
    fi
  done
else
  warn "systemctl command is unavailable; skipped service checks"
fi

echo
echo "Health check finished: failures=${FAILURES} warnings=${WARNINGS}"
[[ "${FAILURES}" -eq 0 ]]

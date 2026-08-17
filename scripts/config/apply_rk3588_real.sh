#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PROFILE_DIR="${REPO_ROOT}/config/profiles/rk3588-real"

source "${SCRIPT_DIR}/profile_common.sh"

profile_require_send_commands_off "${REPO_ROOT}/config/app.yaml"
profile_apply "${REPO_ROOT}" "${PROFILE_DIR}"

echo "Applied RK3588 real profile."
echo "  telemetry: real eth udpin 0.0.0.0:15001"
echo "  video:     /dev/video41"
echo "  optional:  action_missions and missions/*/config.yaml if present in profile"
echo "Review config/yolo.yaml if the camera device path differs on this board."

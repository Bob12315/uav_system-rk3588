#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PROFILE_DIR="${REPO_ROOT}/config/profiles/rk3588-sitl"

source "${SCRIPT_DIR}/profile_common.sh"

profile_require_send_commands_off "${REPO_ROOT}/config/app.yaml"
profile_save "${REPO_ROOT}" "${PROFILE_DIR}"

echo "Saved current active configuration to RK3588 SITL profile:"
profile_print_saved_files "${REPO_ROOT}" "${PROFILE_DIR}"

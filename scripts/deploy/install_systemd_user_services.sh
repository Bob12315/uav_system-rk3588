#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SOURCE_DIR="${REPO_ROOT}/deploy/systemd"
TARGET_DIR="${TARGET_DIR:-${HOME}/.config/systemd/user}"
APP_PYTHON="${APP_PYTHON:-${HOME}/anaconda3/envs/app/bin/python}"
YOLO_PYTHON="${YOLO_PYTHON:-${HOME}/anaconda3/envs/yolo/bin/python}"

ENABLE_NOW=false
DRY_RUN=false

usage() {
  echo "Usage: $0 [--enable-now] [--dry-run]"
}

for arg in "$@"; do
  case "${arg}" in
    --enable-now) ENABLE_NOW=true ;;
    --dry-run) DRY_RUN=true ;;
    *)
      usage >&2
      exit 1
      ;;
  esac
done

if [[ ! -x "${APP_PYTHON}" ]]; then
  echo "Missing app environment Python: ${APP_PYTHON}" >&2
  exit 1
fi

if [[ ! -x "${YOLO_PYTHON}" ]]; then
  echo "Missing YOLO environment Python: ${YOLO_PYTHON}" >&2
  exit 1
fi

escape_sed_replacement() {
  printf '%s' "$1" | sed 's/[&|\\]/\\&/g'
}

render_service() {
  local source="$1"
  local target="$2"
  local repo_root app_python yolo_python
  repo_root="$(escape_sed_replacement "${REPO_ROOT}")"
  app_python="$(escape_sed_replacement "${APP_PYTHON}")"
  yolo_python="$(escape_sed_replacement "${YOLO_PYTHON}")"
  sed \
    -e "s|@REPO_ROOT@|${repo_root}|g" \
    -e "s|@APP_PYTHON@|${app_python}|g" \
    -e "s|@YOLO_PYTHON@|${yolo_python}|g" \
    "${source}" > "${target}"
}

if [[ "${DRY_RUN}" == true ]]; then
  temp_dir="$(mktemp -d)"
  trap 'rm -rf "${temp_dir}"' EXIT
  render_service "${SOURCE_DIR}/uav-app.service" "${temp_dir}/uav-app.service"
  render_service "${SOURCE_DIR}/uav-yolo.service" "${temp_dir}/uav-yolo.service"
  echo "Dry run only. Rendered services:"
  echo
  cat "${temp_dir}/uav-app.service"
  echo
  cat "${temp_dir}/uav-yolo.service"
  exit 0
fi

mkdir -p "${TARGET_DIR}"
render_service "${SOURCE_DIR}/uav-app.service" "${TARGET_DIR}/uav-app.service"
render_service "${SOURCE_DIR}/uav-yolo.service" "${TARGET_DIR}/uav-yolo.service"
systemctl --user daemon-reload

echo "Installed user services:"
echo "  ${TARGET_DIR}/uav-app.service"
echo "  ${TARGET_DIR}/uav-yolo.service"
echo "Repository: ${REPO_ROOT}"
echo "App Python: ${APP_PYTHON}"
echo "YOLO Python: ${YOLO_PYTHON}"

if [[ "${ENABLE_NOW}" == true ]]; then
  systemctl --user enable --now uav-app.service uav-yolo.service
  echo "Enabled and started uav-app.service and uav-yolo.service."
else
  echo "Services were not started."
  echo "Enable them when ready:"
  echo "  systemctl --user enable --now uav-app.service uav-yolo.service"
fi

echo
echo "For startup without an interactive login, run once:"
echo "  sudo loginctl enable-linger \"${USER}\""

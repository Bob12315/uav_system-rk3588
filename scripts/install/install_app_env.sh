#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

APP_ENV_NAME="${APP_ENV_NAME:-app}"
APP_PYTHON_VERSION="${APP_PYTHON_VERSION:-3.10}"

TUNA_PYPI_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"

APT_PACKAGES=(
  git
  curl
  wget
  build-essential
  v4l-utils
  ffmpeg
  libgl1
  libglib2.0-0
  gstreamer1.0-tools
  gstreamer1.0-plugins-base
  gstreamer1.0-plugins-good
  gstreamer1.0-plugins-bad
  gstreamer1.0-plugins-ugly
  gstreamer1.0-libav
)

TOTAL_STEPS=5
CURRENT_STEP=0
CURRENT_STEP_NAME="initializing"

if [[ -t 1 && "${NO_COLOR:-}" == "" ]]; then
  RED="$(printf '\033[31m')"
  GREEN="$(printf '\033[32m')"
  YELLOW="$(printf '\033[33m')"
  BLUE="$(printf '\033[34m')"
  BOLD="$(printf '\033[1m')"
  RESET="$(printf '\033[0m')"
else
  RED=""
  GREEN=""
  YELLOW=""
  BLUE=""
  BOLD=""
  RESET=""
fi

info() {
  echo
  echo "${BLUE}${BOLD}==>${RESET} $*"
}

warn() {
  echo "${YELLOW}${BOLD}WARN:${RESET} $*"
}

progress_bar() {
  local current="$1"
  local total="$2"
  local width=24
  local filled=$((current * width / total))
  local empty=$((width - filled))
  local bar=""

  printf -v bar "%*s" "${filled}" ""
  bar="${bar// /#}"
  printf "%s[%s" "${GREEN}" "${bar}"
  printf "%*s" "${empty}" "" | tr ' ' '-'
  printf "]%s %d/%d" "${RESET}" "${current}" "${total}"
}

step() {
  CURRENT_STEP=$((CURRENT_STEP + 1))
  CURRENT_STEP_NAME="$*"
  echo
  progress_bar "${CURRENT_STEP}" "${TOTAL_STEPS}"
  echo "  ${BOLD}$*${RESET}"
}

print_failure() {
  local exit_code="$1"
  echo
  echo "${RED}${BOLD}INSTALL FAILED${RESET}"
  echo "${RED}Failed step:${RESET} ${CURRENT_STEP}/${TOTAL_STEPS} ${CURRENT_STEP_NAME}"
  echo "${RED}Exit code:${RESET} ${exit_code}"
  echo "Check the error output above, fix the issue, then run this script again."
}

die() {
  echo "${RED}${BOLD}ERROR:${RESET} $*" >&2
  print_failure 1 >&2
  exit 1
}

on_error() {
  local exit_code="$?"
  print_failure "${exit_code}" >&2
  exit "${exit_code}"
}

on_success() {
  echo
  echo "${GREEN}${BOLD}INSTALL SUCCEEDED${RESET}"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "'$1' was not found."
}

check_linux_arm64() {
  step "Checking RK3588 system architecture"
  local kernel
  kernel="$(uname -s)"
  [[ "${kernel}" == "Linux" ]] || die "This RK3588 installer currently supports Linux only. Detected: ${kernel}"

  local arch
  arch="$(uname -m)"
  [[ "${arch}" == "aarch64" || "${arch}" == "arm64" ]] || die "This RK3588 branch requires aarch64/arm64. Detected: ${arch}"
  echo "${GREEN}OK:${RESET} ${kernel} ${arch}"
}

check_conda_env() {
  step "Checking conda environment"
  require_command conda

  [[ -n "${CONDA_DEFAULT_ENV:-}" ]] || die "No active conda environment. Run: conda activate ${APP_ENV_NAME}"
  [[ "${CONDA_DEFAULT_ENV}" == "${APP_ENV_NAME}" ]] || die "Please activate conda env '${APP_ENV_NAME}' first. Current env: ${CONDA_DEFAULT_ENV}"

  local actual_python
  actual_python="$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  [[ "${actual_python}" == "${APP_PYTHON_VERSION}" ]] || die "Python ${APP_PYTHON_VERSION}.x is required for env '${APP_ENV_NAME}'. Current: ${actual_python}"
  echo "${GREEN}OK:${RESET} conda env '${CONDA_DEFAULT_ENV}', Python ${actual_python}.x"
}

install_system_deps() {
  step "Installing system packages"
  if ! command -v apt-get >/dev/null 2>&1; then
    warn "Skipping system package installation: apt-get was not found."
    echo "Install equivalent packages manually: ${APT_PACKAGES[*]}"
    return
  fi

  info "Installing Ubuntu/Debian system packages"
  if [[ "${EUID}" -eq 0 ]]; then
    apt-get update
    apt-get install -y "${APT_PACKAGES[@]}"
  else
    require_command sudo
    sudo apt-get update
    sudo apt-get install -y "${APT_PACKAGES[@]}"
  fi
}

install_python_deps() {
  step "Installing app Python packages"
  info "Installing app dependencies from requirements-app.txt"
  python -m pip install -i "${TUNA_PYPI_INDEX}" --upgrade pip
  python -m pip install -i "${TUNA_PYPI_INDEX}" -r "${REPO_ROOT}/requirements-app.txt"
}

verify_app_env() {
  step "Verifying app environment"
  info "Verifying app environment"
  python - <<'PY'
import numpy
import pymavlink
import pytest
import yaml
import fastapi
import httpx
import uvicorn

print("python import check passed")
print("numpy", numpy.__version__)
print("pytest", pytest.__version__)
PY

  cd "${REPO_ROOT}"
  python -m app.main --help >/dev/null
  python -m telemetry_link.main --help >/dev/null
  echo "App command checks passed"
}

main() {
  trap on_error ERR

  check_linux_arm64
  check_conda_env
  install_system_deps
  install_python_deps
  verify_app_env

  trap - ERR
  on_success

  info "Done"
  echo "App environment '${APP_ENV_NAME}' is ready for RK3588."
  echo "Install the separate YOLO environment with:"
  echo "  bash ${REPO_ROOT}/scripts/install/install_yolo_env.sh"
  echo "Try:"
  echo "  cd ${REPO_ROOT}"
  echo "  python -m app.main --no-yolo-udp --run-seconds 1 --send-commands false --no-ui --blackbox-enabled false"
}

main "$@"

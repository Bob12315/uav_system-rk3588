#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "This project no longer creates conda environments automatically."
echo "Create and activate the RK3588 app environment first:"
echo "  conda create -n app python=3.10 -y"
echo "  conda activate app"
echo
echo "Then run:"
echo "  bash ${SCRIPT_DIR}/install_app_env.sh"
echo
echo "Forwarding to install_app_env.sh now..."
exec bash "${SCRIPT_DIR}/install_app_env.sh"

#!/usr/bin/env bash
set -euo pipefail

echo "Lock refresh is intentionally explicit: resolve separately on Linux x86_64 and Linux ARM64."
echo "Use pip-tools in each matching environment, review licenses, then update requirements/locks/ manually."
echo "Example: pip-compile --generate-hashes -o requirements/locks/linux-64.txt requirements/app.txt"
echo "RK3588 YOLO must additionally pass scripts/healthcheck/check_rk3588.sh before its vendor lock changes."

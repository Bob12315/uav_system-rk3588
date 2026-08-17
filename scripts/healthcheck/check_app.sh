#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

python - <<'PY'
from pathlib import Path

import yaml

app = yaml.safe_load(Path("config/app.yaml").read_text(encoding="utf-8"))
assert app["executor"]["send_commands"] is False
PY
python -m app.main --help >/dev/null
python scripts/validate_action_missions.py >/dev/null
echo "Generic app health check passed (perception_source=disabled is supported)."

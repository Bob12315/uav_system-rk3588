from __future__ import annotations

import re
from pathlib import Path


def test_drop_two_targets_v2_display_label() -> None:
    """drop_two_targets_v2 在 Web UI 中的中文显示名应为 投放任务 v2。"""
    text = Path("web_ui/server.py").read_text(encoding="utf-8")
    match = re.search(r'"drop_two_targets_v2":\s*"([^"]+)"', text)
    assert match is not None, "drop_two_targets_v2 display label not found in web_ui/server.py"
    assert match.group(1) == "投放任务 v2"

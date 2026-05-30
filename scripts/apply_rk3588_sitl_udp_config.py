#!/usr/bin/env python3
"""Apply RK3588 configs for PC SITL UDP mavlink + UDP5600 video."""
from __future__ import annotations

import os
import re
import textwrap

import pexpect

BOARD = os.environ.get("BOARD", "pi@10.31.18.109")
PASSWORD = os.environ.get("BOARD_SSH_PASS", "")
PROJ = os.environ.get("BOARD_PROJ", "$HOME/uav_system-rk3588")


def ssh(script: str, timeout: int = 90) -> str:
    child = pexpect.spawn(
        f"ssh -o StrictHostKeyChecking=accept-new -o PreferredAuthentications=password "
        f"-o PubkeyAuthentication=no {BOARD} bash -s",
        encoding="utf-8",
        timeout=timeout,
    )
    while True:
        idx = child.expect(
            ["password:", r"Are you sure you want to continue connecting", pexpect.EOF, pexpect.TIMEOUT],
            timeout=30,
        )
        if idx == 0:
            child.sendline(PASSWORD)
        elif idx == 1:
            child.sendline("yes")
        else:
            break
    child.send(script)
    child.sendeof()
    child.expect(pexpect.EOF, timeout=timeout)
    return str(child.before or "")


def main() -> int:
    if not PASSWORD:
        print("Set BOARD_SSH_PASS", file=__import__("sys").stderr)
        return 1
    remote = textwrap.dedent(
        f"""
        set -e
        PROJ={PROJ}
        TELEM="$PROJ/config/telemetry.yaml"
        YOLO="$PROJ/yolo_app/config.yaml"
        test -f "$TELEM" && test -f "$YOLO"

        python3 - "$TELEM" "$YOLO" <<'PY'
import re, sys
from pathlib import Path

telem_path, yolo_path = map(Path, sys.argv[1:3])
t = telem_path.read_text()
t = re.sub(r"^data_source:.*$", "data_source: sitl", t, count=1, flags=re.M)
t = re.sub(r"^active_source:.*$", "active_source: sitl", t, count=1, flags=re.M)
t = re.sub(
    r"(^sitl:\\n(?:.*\\n)*?  connection_type: ).*$",
    r"\\g<1>udp",
    t,
    count=1,
    flags=re.M,
)
t = re.sub(
    r"(^sitl:\\n(?:.*\\n)*?  udp_mode: ).*$",
    r"\\g<1>udpin",
    t,
    count=1,
    flags=re.M,
)
t = re.sub(
    r"(^sitl:\\n(?:.*\\n)*?  udp_host: ).*$",
    r"\\g<1>0.0.0.0",
    t,
    count=1,
    flags=re.M,
)
t = re.sub(
    r"(^sitl:\\n(?:.*\\n)*?  udp_port: ).*$",
    r"\\g<1>14550",
    t,
    count=1,
    flags=re.M,
)
telem_path.write_text(t)

y = yolo_path.read_text()
y = re.sub(r"^source:.*$", "source: 5600", y, count=1, flags=re.M)
y = re.sub(r'^udp_ip:.*$', 'udp_ip: "127.0.0.1"', y, count=1, flags=re.M)
y = re.sub(r"^udp_port:.*$", "udp_port: 5005", y, count=1, flags=re.M)
yolo_path.write_text(y)
print("ok")
PY

        sed -i 's/^  connect_telemetry:.*/  connect_telemetry: true/' "$PROJ/config/app.yaml"
        sed -i 's/^  send_commands:.*/  send_commands: false/' "$PROJ/config/app.yaml"

        echo "--- sitl ---"
        sed -n '/^sitl:/,/^real:/p' "$TELEM" | head -12
        echo "--- yolo ---"
        grep -E '^source:|^udp_' "$YOLO"

        systemctl --user daemon-reload 2>/dev/null || true
        if systemctl --user is-enabled uav-app.service >/dev/null 2>&1; then
          systemctl --user restart uav-yolo.service uav-app.service
          sleep 3
          systemctl --user is-active uav-yolo uav-app
        else
          echo "systemd not enabled; restart yolo/app manually"
        fi
        """
    )
    print(ssh(remote))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

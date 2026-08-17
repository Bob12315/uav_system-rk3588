"""Regression tests for the field-reference snapshot deadlock fix.

The deadlock chain (before fix):
  _action_lab_only_loop() acquires control_command_log_lock (threading.Lock)
  → calls field_service.status()
  → _drone_snapshot_for_controller() tries to re-acquire the same lock
  → DEADLOCK (threading.Lock is not re-entrant)

Fix: field_service.status() is called *before* the lock,
and only the pre-computed dict is assigned inside the lock.
"""
from __future__ import annotations

import threading
import time

import pytest

from app.config import build_arg_parser, load_app_config
from application.runner import SystemRunner


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_runner():
    """Build a minimal SystemRunner with telemetry and YOLO disabled."""
    args = build_arg_parser().parse_args(
        ["--run-seconds", "0.1", "--no-yolo-udp"]
    )
    config = load_app_config(args)
    return SystemRunner(config)


# ---------------------------------------------------------------------------
# Test 1: main loop single iteration must not deadlock
# ---------------------------------------------------------------------------


def test_action_lab_only_loop_does_not_deadlock():
    """_action_lab_only_loop must complete at least one iteration without hanging.

    The runner is configured with --run-seconds=0.1 so the loop will exit
    quickly.  A threading.Lock deadlock would cause the thread to block
    forever and fail the join(timeout=10).
    """
    runner = _make_runner()

    # Verify we are using a plain Lock, not RLock (structural requirement)
    assert type(runner.control_command_log_lock) is type(threading.Lock()), (
        "control_command_log_lock must be threading.Lock, not RLock"
    )

    loop_thread = threading.Thread(
        target=runner._action_lab_only_loop,
        name="test-deadlock-loop",
        daemon=True,
    )
    loop_thread.start()

    loop_thread.join(timeout=10.0)

    assert not loop_thread.is_alive(), (
        "_action_lab_only_loop did not exit within 10 s — likely deadlocked "
        "on control_command_log_lock"
    )

    # After the loop exits, the snapshot should contain field_reference.
    snapshot = runner.state_store.read()
    assert isinstance(snapshot, dict), "state snapshot should be a dict"
    assert "field_reference" in snapshot, (
        "state snapshot missing 'field_reference' key"
    )


# ---------------------------------------------------------------------------
# Test 2: field_service.status() must NOT be called inside
#         the control_command_log_lock
# ---------------------------------------------------------------------------


class _LockDetectingController:
    """Wraps FieldService to detect lock-held calls."""

    def __init__(self, real_controller, lock: threading.Lock):
        self._real = real_controller
        self._lock = lock

    def status(self):
        if self._lock.locked():
            raise AssertionError(
                "field_service.status() called while "
                "control_command_log_lock is held — this is the deadlock pattern"
            )
        return self._real.status()

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_status_not_called_inside_lock():
    """field_service.status() must never be called while
    control_command_log_lock is held."""
    runner = _make_runner()

    # Wrap the controller so that status() asserts the lock is NOT held.
    runner.field_service = _LockDetectingController(
        runner.field_service, runner.control_command_log_lock
    )

    loop_thread = threading.Thread(
        target=runner._action_lab_only_loop,
        name="test-lock-detector",
        daemon=True,
    )
    loop_thread.start()
    loop_thread.join(timeout=10.0)

    assert not loop_thread.is_alive(), (
        "_action_lab_only_loop did not exit — likely deadlocked or "
        "raised inside lock"
    )


# ---------------------------------------------------------------------------
# Test 3: web_status_snapshot must not hang on a held lock
# ---------------------------------------------------------------------------


def test_web_status_snapshot_returns_without_deadlock():
    """web_status_snapshot() must return promptly even when the main loop
    is (or was) running."""
    runner = _make_runner()

    # Run the loop briefly in background
    loop_thread = threading.Thread(
        target=runner._action_lab_only_loop,
        name="test-loop",
        daemon=True,
    )
    loop_thread.start()

    # While the loop runs (or after it exits), snapshot must not hang.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        snapshot = runner.web_status_snapshot()
        assert isinstance(snapshot, dict), "web_status_snapshot must return a dict"
        if not loop_thread.is_alive():
            break
        time.sleep(0.05)

    loop_thread.join(timeout=1.0)


# ---------------------------------------------------------------------------
# Test 4: asyncio.to_thread is used in the WebSocket handler
# ---------------------------------------------------------------------------


def test_websocket_handler_uses_to_thread():
    """The /ws/status handler must use asyncio.to_thread() to isolate
    synchronous lock acquisition from the event loop."""
    import ast
    from pathlib import Path

    server_path = (
        Path(__file__).resolve().parents[3] / "web_ui" / "api_routers.py"
    )
    source = server_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Find the status_socket async function
    found_to_thread = False
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "status_socket":
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    func = child.func
                    if (
                        isinstance(func, ast.Attribute)
                        and func.attr == "to_thread"
                        and isinstance(func.value, ast.Name)
                        and func.value.id == "asyncio"
                    ):
                        found_to_thread = True
                        break
            break

    assert found_to_thread, (
        "status_socket must use asyncio.to_thread() for web_status_snapshot"
    )

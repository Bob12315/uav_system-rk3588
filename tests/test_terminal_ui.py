from __future__ import annotations

from uav_ui.terminal_ui import complete_command_input


def test_complete_unique_command() -> None:
    result = complete_command_input("target un", len("target un"))

    assert result.buffer == "target unlock"
    assert result.cursor == len("target unlock")
    assert "1/1" in result.message


def test_complete_cycles_multiple_matches() -> None:
    first = complete_command_input("tar", len("tar"))
    second = complete_command_input(first.buffer, first.cursor, first.state)

    assert first.buffer == "target "
    assert second.buffer == "target lock "
    assert second.cursor == len("target lock ")


def test_complete_preserves_suffix_after_cursor() -> None:
    prefix = "mode GU"
    suffix = " --later"
    result = complete_command_input(prefix + suffix, len(prefix))

    assert result.buffer == "mode GUIDED --later"
    assert result.cursor == len("mode GUIDED")


def test_complete_reports_no_match_without_changing_input() -> None:
    result = complete_command_input("zz", 2)

    assert result.buffer == "zz"
    assert result.cursor == 2
    assert result.message == "no completion"


def test_complete_pid_reload_command() -> None:
    result = complete_command_input("pid r", len("pid r"))

    assert result.buffer == "pid reload"


def test_complete_stage_override_command() -> None:
    result = complete_command_input("stage mode OVER", len("stage mode OVER"))

    assert result.buffer == "stage mode OVERHEAD_HOLD"


def test_complete_mission_switch_command() -> None:
    result = complete_command_input("mission switch resc", len("mission switch resc"))

    assert result.buffer == "mission switch rescue_competition"

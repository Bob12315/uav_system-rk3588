from __future__ import annotations

import curses
import sys
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

from telemetry_link.command_dispatcher import CommandResult, dispatch_text_command
from telemetry_link.link_manager import LinkManager
from uav_ui.completion_catalog import COMMAND_COMPLETIONS


@dataclass(slots=True)
class UiCommandLog:
    timestamp: float
    command: str
    ok: bool
    message: str


@dataclass(slots=True)
class AutocompleteState:
    seed: str = ""
    matches: tuple[str, ...] = ()
    index: int = -1


@dataclass(slots=True)
class AutocompleteResult:
    buffer: str
    cursor: int
    state: AutocompleteState
    message: str


def complete_command_input(buffer: str, cursor: int, state: AutocompleteState | None = None) -> AutocompleteResult:
    state = state or AutocompleteState()
    cursor = max(0, min(cursor, len(buffer)))
    prefix = buffer[:cursor]
    suffix = buffer[cursor:]
    current_match = state.matches[state.index] if 0 <= state.index < len(state.matches) else ""
    if state.matches and prefix in {state.seed, current_match}:
        matches = state.matches
        index = (state.index + 1) % len(matches)
    else:
        lowered = prefix.lower()
        matches = tuple(candidate for candidate in COMMAND_COMPLETIONS if candidate.lower().startswith(lowered))
        index = 0
    if not matches:
        return AutocompleteResult(buffer, cursor, AutocompleteState(), "no completion")
    candidate = matches[index]
    next_buffer = candidate + suffix
    next_state = AutocompleteState(seed=prefix, matches=matches, index=index)
    if len(matches) == 1:
        message = f"completion 1/1: {candidate}"
    else:
        message = f"completion {index + 1}/{len(matches)}: {candidate}"
    return AutocompleteResult(next_buffer, len(candidate), next_state, message)


def run_terminal_ui(
    manager: LinkManager,
    stop_event,
    mission_control_lines: Callable[[], list[str]] | None = None,
    command_handler: Callable[[str], CommandResult] | None = None,
) -> None:
    curses.wrapper(
        lambda stdscr: _TelemetryTerminalUi(
            stdscr,
            manager,
            stop_event,
            mission_control_lines,
            command_handler,
        ).run()
    )


class _TelemetryTerminalUi:
    def __init__(
        self,
        stdscr,
        manager: LinkManager,
        stop_event,
        mission_control_lines: Callable[[], list[str]] | None,
        command_handler: Callable[[str], CommandResult] | None,
    ) -> None:
        self.stdscr = stdscr
        self.manager = manager
        self.stop_event = stop_event
        self.mission_control_lines = mission_control_lines
        self.command_handler = command_handler or (lambda command: dispatch_text_command(self.manager, command))
        self.input_buffer = ""
        self.input_cursor = 0
        self.draft_buffer = ""
        self.history: list[str] = []
        self.history_index: int | None = None
        self.command_log: deque[UiCommandLog] = deque(maxlen=80)
        self.last_draw = 0.0
        self.autocomplete_state = AutocompleteState()
        self.autocomplete_message = ""

    def run(self) -> None:
        curses.curs_set(1)
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_RED, -1)
        curses.init_pair(3, curses.COLOR_CYAN, -1)
        self.stdscr.nodelay(True)
        self.stdscr.keypad(True)
        self._set_bracketed_paste(True)

        try:
            while not self.stop_event.is_set():
                self._handle_input()
                now = time.time()
                if now - self.last_draw >= 0.1:
                    self._draw()
                    self.last_draw = now
                time.sleep(0.02)
        finally:
            self._set_bracketed_paste(False)

    def _handle_input(self) -> None:
        while True:
            try:
                first_ch = self.stdscr.get_wch()
            except curses.error:
                return

            if first_ch == "\x1b":
                if self._handle_escape_sequence():
                    continue
                self.stop_event.set()
                return

            chars = [first_ch]
            chars.extend(self._drain_available_chars())
            paste_mode = len(chars) > 1 and any(ch in ("\n", "\r") for ch in chars)
            if paste_mode:
                pasted = "".join(
                    " " if ch in ("\n", "\r") else ch
                    for ch in chars
                    if isinstance(ch, str) and (ch in ("\n", "\r") or ch.isprintable())
                )
                self._append_pasted_text(pasted)
                continue
            for ch in chars:
                self._handle_char(ch)

    def _handle_char(self, ch, paste_mode: bool = False) -> None:
        if paste_mode and ch in ("\n", "\r"):
            self._append_pasted_text(" ")
            return
        if paste_mode:
            if isinstance(ch, str) and ch.isprintable():
                self._append_pasted_text(ch)
            return

        if ch in ("\n", "\r"):
            self._submit_input()
        elif ch == "\x03":
            self.stop_event.set()
            return
        elif ch == "\x1b":
            self.stop_event.set()
            return
        elif ch in (curses.KEY_BACKSPACE, "\b", "\x7f"):
            self._leave_history()
            self._delete_before_cursor()
        elif ch == curses.KEY_DC:
            self._leave_history()
            self._delete_at_cursor()
        elif ch == curses.KEY_LEFT:
            self.input_cursor = max(0, self.input_cursor - 1)
        elif ch == curses.KEY_RIGHT:
            self.input_cursor = min(len(self.input_buffer), self.input_cursor + 1)
        elif ch == curses.KEY_HOME or ch == "\x01":
            self.input_cursor = 0
        elif ch == curses.KEY_END or ch == "\x05":
            self.input_cursor = len(self.input_buffer)
        elif ch == curses.KEY_UP:
            self._history_prev()
        elif ch == curses.KEY_DOWN:
            self._history_next()
        elif ch == "\t":
            self._autocomplete()
        elif ch == curses.KEY_RESIZE:
            return
        elif isinstance(ch, str) and ch.isprintable():
            self._leave_history()
            self._reset_autocomplete()
            self._insert_text(ch)

    def _handle_escape_sequence(self) -> bool:
        sequence = "".join(str(ch) for ch in self._drain_available_chars(wait_sec=0.03))
        if sequence.startswith("[200~"):
            pasted = sequence.removeprefix("[200~")
            self._read_bracketed_paste(pasted)
            return True
        if sequence in {"[D", "OD"}:
            self.input_cursor = max(0, self.input_cursor - 1)
            return True
        if sequence in {"[C", "OC"}:
            self.input_cursor = min(len(self.input_buffer), self.input_cursor + 1)
            return True
        if sequence in {"[H", "OH", "[1~", "[7~"}:
            self.input_cursor = 0
            return True
        if sequence in {"[F", "OF", "[4~", "[8~"}:
            self.input_cursor = len(self.input_buffer)
            return True
        if sequence == "[3~":
            self._leave_history()
            self._delete_at_cursor()
            return True
        return bool(sequence)

    def _read_bracketed_paste(self, initial_text: str) -> None:
        buffer = initial_text
        deadline = time.time() + 2.0
        while "\x1b[201~" not in buffer and time.time() < deadline:
            try:
                ch = self.stdscr.get_wch()
            except curses.error:
                time.sleep(0.005)
                continue
            buffer += str(ch)
        pasted, _, _tail = buffer.partition("\x1b[201~")
        self._append_pasted_text(pasted)

    def _append_pasted_text(self, text: str) -> None:
        normalized = " ".join(text.replace("\r", "\n").splitlines())
        if not normalized:
            return
        self._leave_history()
        self._reset_autocomplete()
        prefix = " " if self.input_buffer and self.input_cursor == len(self.input_buffer) and not self.input_buffer.endswith(" ") else ""
        self._insert_text(prefix + normalized)

    def _insert_text(self, text: str) -> None:
        if not text:
            return
        self.input_buffer = (
            self.input_buffer[: self.input_cursor]
            + text
            + self.input_buffer[self.input_cursor :]
        )
        self.input_cursor += len(text)

    def _delete_before_cursor(self) -> None:
        if self.input_cursor <= 0:
            return
        self._reset_autocomplete()
        self.input_buffer = (
            self.input_buffer[: self.input_cursor - 1]
            + self.input_buffer[self.input_cursor :]
        )
        self.input_cursor -= 1

    def _delete_at_cursor(self) -> None:
        if self.input_cursor >= len(self.input_buffer):
            return
        self._reset_autocomplete()
        self.input_buffer = (
            self.input_buffer[: self.input_cursor]
            + self.input_buffer[self.input_cursor + 1 :]
        )

    def _drain_available_chars(self, wait_sec: float = 0.0) -> list:
        chars = []
        deadline = time.time() + wait_sec
        while True:
            try:
                chars.append(self.stdscr.get_wch())
            except curses.error:
                if time.time() >= deadline:
                    return chars
                time.sleep(0.005)

    def _set_bracketed_paste(self, enabled: bool) -> None:
        sys.stdout.write("\x1b[?2004h" if enabled else "\x1b[?2004l")
        sys.stdout.flush()

    def _submit_input(self) -> None:
        command = self.input_buffer.strip()
        self.input_buffer = ""
        self.input_cursor = 0
        self.draft_buffer = ""
        self.history_index = None
        self._reset_autocomplete()
        if command in {"quit", "exit"}:
            self.stop_event.set()
            return
        if not command:
            return
        if not self.history or self.history[-1] != command:
            self.history.append(command)
        result = self.command_handler(command)
        self.command_log.appendleft(
            UiCommandLog(
                timestamp=time.time(),
                command=command,
                ok=result.ok,
                message=result.message,
            )
        )

    def _history_prev(self) -> None:
        if not self.history:
            return
        if self.history_index is None:
            self.draft_buffer = self.input_buffer
            self.history_index = len(self.history) - 1
        else:
            self.history_index = max(0, self.history_index - 1)
        self.input_buffer = self.history[self.history_index]
        self.input_cursor = len(self.input_buffer)
        self._reset_autocomplete()

    def _history_next(self) -> None:
        if self.history_index is None:
            return
        if self.history_index >= len(self.history) - 1:
            self.history_index = None
            self.input_buffer = self.draft_buffer
            self.input_cursor = len(self.input_buffer)
            self.draft_buffer = ""
            self._reset_autocomplete()
            return
        self.history_index += 1
        self.input_buffer = self.history[self.history_index]
        self.input_cursor = len(self.input_buffer)
        self._reset_autocomplete()

    def _leave_history(self) -> None:
        if self.history_index is not None:
            self.history_index = None
            self.draft_buffer = ""

    def _autocomplete(self) -> None:
        self._leave_history()
        result = complete_command_input(self.input_buffer, self.input_cursor, self.autocomplete_state)
        self.input_buffer = result.buffer
        self.input_cursor = result.cursor
        self.autocomplete_state = result.state
        self.autocomplete_message = result.message

    def _reset_autocomplete(self) -> None:
        self.autocomplete_state = AutocompleteState()
        self.autocomplete_message = ""

    def _draw(self) -> None:
        height, width = self.stdscr.getmaxyx()
        self.stdscr.erase()
        if height < 14 or width < 60:
            self._addstr(0, 0, "Terminal too small. Resize to at least 60x14.")
            self.stdscr.refresh()
            return

        left_width = max(34, width // 2)
        right_width = width - left_width
        top_height = height - 3
        command_height = max(7, top_height // 2)
        control_height = top_height - command_height
        self._draw_box(0, 0, top_height, left_width, "Latest telemetry")
        self._draw_box(0, left_width, command_height, right_width, "Manual commands")
        self._draw_box(command_height, left_width, control_height, right_width, "Mission control")
        self._draw_input_line(height - 3, width)
        self._draw_status_line(height - 1, width)
        self._draw_latest(1, 2, top_height - 2, left_width - 4)
        self._draw_commands(1, left_width + 2, command_height - 2, right_width - 4)
        self._draw_mission_control(
            command_height + 1,
            left_width + 2,
            control_height - 2,
            right_width - 4,
        )
        self._move_input_cursor(height - 3, width)
        self.stdscr.refresh()

    def _draw_box(self, y: int, x: int, h: int, w: int, title: str) -> None:
        if h <= 0 or w <= 0:
            return
        win = self.stdscr.derwin(h, w, y, x)
        win.box()
        title_text = f" {title} "
        try:
            win.addstr(0, 2, title_text[: max(0, w - 4)], curses.A_BOLD)
        except curses.error:
            pass

    def _draw_latest(self, y: int, x: int, h: int, w: int) -> None:
        state = self.manager.get_latest_drone_state()
        gimbal = self.manager.get_latest_gimbal_state()
        link = self.manager.get_link_status()
        active_source = self.manager.get_active_source()
        lines = [
            f"active_source: {active_source}",
            f"link: {link.status_text} reconnecting={link.reconnecting}",
            f"connected={state.connected} stale={state.stale} mode={state.mode} armed={state.armed}",
            f"control_allowed={state.control_allowed}",
            "",
            f"att_valid={state.attitude_valid}",
            f"rpy=({state.roll:.2f}, {state.pitch:.2f}, {state.yaw:.2f})",
            f"rates=({state.roll_rate:.2f}, {state.pitch_rate:.2f}, {state.yaw_rate:.2f})",
            "",
            f"alt_valid={state.altitude_valid} alt={state.altitude:.2f} rel={state.relative_altitude:.2f}",
            f"vel_valid={state.velocity_valid} vel=({state.vx:.2f}, {state.vy:.2f}, {state.vz:.2f})",
            f"vel_src={state.velocity_source} quality={state.velocity_quality}",
            f"pos_valid={state.global_position_valid}",
            f"lat={state.lat:.7f} lon={state.lon:.7f}",
            "",
            f"battery_valid={state.battery_valid} voltage={state.battery_voltage:.2f}V",
            f"battery_remaining={state.battery_remaining} gps_fix={state.gps_fix_type} sats={state.satellites_visible}",
            "",
            f"gimbal_valid={gimbal.gimbal_valid} src={gimbal.source_msg_type}",
            f"gimbal_rpy=({gimbal.roll:.2f}, {gimbal.pitch:.2f}, {gimbal.yaw:.2f})",
            "",
            f"hb_age={state.hb_age_sec:.2f}s rx_age={state.rx_age_sec:.2f}s",
            f"last_tx_age={self._age(link.last_tx_time)}",
        ]
        for index, line in enumerate(lines[:h]):
            self._addstr(y + index, x, line[:w], self._line_attr(line))

    def _draw_commands(self, y: int, x: int, h: int, w: int) -> None:
        for index, item in enumerate(list(self.command_log)[:h]):
            time_text = time.strftime("%H:%M:%S", time.localtime(item.timestamp))
            marker = "OK" if item.ok else "ERR"
            line = f"{time_text} [{marker}] {item.command} -> {item.message}"
            attr = curses.color_pair(1) if item.ok else curses.color_pair(2)
            self._addstr(y + index, x, line[:w], attr)

    def _draw_mission_control(self, y: int, x: int, h: int, w: int) -> None:
        if self.mission_control_lines is None:
            self._addstr(y, x, "No mission control source.", curses.A_DIM)
            return
        lines = self.mission_control_lines()
        if not lines:
            self._addstr(y, x, "Waiting for mission control...", curses.A_DIM)
            return
        for index, line in enumerate(lines[:h]):
            self._addstr(y + index, x, line[:w], self._line_attr(line))

    def _draw_input_line(self, y: int, width: int) -> None:
        prompt = "> "
        self._addstr(y, 0, "-" * max(0, width - 1))
        visible, _cursor_col = self._input_view(width, prompt)
        self._addstr(y + 1, 0, (prompt + visible)[: width - 1], curses.A_BOLD)

    def _move_input_cursor(self, y: int, width: int) -> None:
        prompt = "> "
        _visible, cursor_col = self._input_view(width, prompt)
        try:
            self.stdscr.move(y + 1, cursor_col)
        except curses.error:
            pass

    def _input_view(self, width: int, prompt: str) -> tuple[str, int]:
        self.input_cursor = max(0, min(self.input_cursor, len(self.input_buffer)))
        max_text_width = max(1, width - len(prompt) - 1)
        start = max(0, self.input_cursor - max_text_width)
        if start < len(self.input_buffer) - max_text_width and self.input_cursor == len(self.input_buffer):
            start = max(0, len(self.input_buffer) - max_text_width)
        visible = self.input_buffer[start : start + max_text_width]
        cursor_col = len(prompt) + self.input_cursor - start
        return visible, min(width - 1, max(0, cursor_col))

    def _draw_status_line(self, y: int, width: int) -> None:
        text = "Enter sends command. Tab completes. Up/Down history. Esc/Ctrl-C exits UI."
        if self.autocomplete_message:
            text = f"{text} {self.autocomplete_message}"
        self._addstr(y, 0, text[: width - 1], curses.A_DIM)

    def _addstr(self, y: int, x: int, text: str, attr: int = 0) -> None:
        try:
            self.stdscr.addstr(y, x, text, attr)
        except curses.error:
            pass

    def _line_attr(self, line: str) -> int:
        if "connected=False" in line or "stale=True" in line or "valid=False" in line:
            return curses.color_pair(2)
        if "connected=True" in line or "valid=True" in line:
            return curses.color_pair(1)
        return 0

    def _age(self, timestamp: float) -> str:
        if timestamp <= 0:
            return "never"
        return f"{time.time() - timestamp:.2f}s"

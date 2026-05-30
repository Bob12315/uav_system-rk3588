from __future__ import annotations

import heapq
import threading
import time

try:
    from .models import ActionCommand, ControlCommand, GimbalRateCommand, QueuedAction
except ImportError:  # pragma: no cover - supports direct script execution
    from models import ActionCommand, ControlCommand, GimbalRateCommand, QueuedAction


class CommandQueue:
    """
    Command queue policy:

    - Continuous control commands keep only the latest sample.
    - One-shot action commands are stored in a priority queue.
    - Higher-priority actions can preempt lower-priority pending actions.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest_control: ControlCommand | None = None
        self._latest_gimbal_rate: GimbalRateCommand | None = None
        self._action_heap: list[QueuedAction] = []
        self._sequence = 0

    def put_control(self, command: ControlCommand) -> None:
        with self._lock:
            self._latest_control = command

    def peek_control(self) -> ControlCommand | None:
        with self._lock:
            return self._latest_control

    def clear_control(self) -> None:
        with self._lock:
            self._latest_control = None

    def put_gimbal_rate(self, command: GimbalRateCommand) -> None:
        with self._lock:
            self._latest_gimbal_rate = command

    def peek_gimbal_rate(self) -> GimbalRateCommand | None:
        with self._lock:
            return self._latest_gimbal_rate

    def clear_gimbal_rate(self) -> None:
        with self._lock:
            self._latest_gimbal_rate = None

    def put_action(self, command: ActionCommand) -> None:
        with self._lock:
            self._sequence += 1
            heapq.heappush(
                self._action_heap,
                QueuedAction(priority=command.priority, sequence=self._sequence, command=command),
            )

    def get_next_action(self) -> ActionCommand | None:
        with self._lock:
            if not self._action_heap:
                return None
            item = heapq.heappop(self._action_heap)
            return item.command

    def requeue_action(self, command: ActionCommand) -> None:
        command.created_at = time.time()
        self.put_action(command)

from __future__ import annotations

import logging
import signal
import threading
from pathlib import Path

from app.app_config import build_arg_parser, load_app_config
from app.system_runner import SystemRunner


def setup_logging(level: str, log_file: str | None = None) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        filename=log_file,
    )


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    config = load_app_config(args)
    ui_log_file = str(Path(__file__).with_name("app_ui.log")) if config.runtime.ui_enabled else None
    setup_logging(config.runtime.log_level, ui_log_file)
    logger = logging.getLogger("app.main")
    stop_event = threading.Event()

    def _handle_signal(signum, _frame) -> None:
        logger.info("received signal %s, shutting down", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    runner = SystemRunner(config, stop_event=stop_event)
    runner.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

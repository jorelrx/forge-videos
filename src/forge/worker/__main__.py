"""Worker CLI: poll for pending work and execute stages."""
from __future__ import annotations

import argparse
import signal
import sys
from threading import Event

from forge.infrastructure.config import get_settings
from forge.services.studio import build_worker


def run_loop(worker: object, poll_seconds: float, stopped: Event) -> None:
    """Run the worker loop until stopped."""
    while not stopped.is_set():
        worker.run_once()
        stopped.wait(poll_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="forge-worker",
        description="Forge studio worker process",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single iteration and exit",
    )
    parser.add_argument(
        "--worker-id",
        default="forge-worker",
        help="Worker identifier (default: forge-worker)",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    worker = build_worker(settings, worker_id=args.worker_id)

    stopped = Event()

    def _signal_handler(signum: int, frame: object) -> None:
        stopped.set()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    if args.once:
        worker.run_once()
        return 0

    run_loop(worker, poll_seconds=settings.studio_worker_poll_seconds, stopped=stopped)
    return 0


if __name__ == "__main__":
    sys.exit(main())

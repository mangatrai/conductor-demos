"""Start all dispute workers (one polling process per task type).

    python -m workers.run_workers      (from dispute_demo/)
"""

import signal
import sys

from conductor.client.automator.task_handler import TaskHandler
from conductor.client.configuration.configuration import Configuration

from app.orkes import flavor, load_env
import workers.dispute_workers  # noqa: F401  (registers the @worker_task functions)


def main() -> None:
    load_env()
    config = Configuration()
    if flavor() == "oss":
        config.authentication_settings = None  # OSS has no login; don't send keys even if .env has them
    handler = TaskHandler(configuration=config, scan_for_annotated_workers=True)
    handler.start_processes()

    def stop(*_):  # also stop the per-task worker processes on SIGTERM, not only on Ctrl+C
        handler.stop_processes()
        sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    print("Dispute workers polling. Ctrl+C to stop.", flush=True)
    try:
        handler.join_processes()
    except KeyboardInterrupt:
        handler.stop_processes()


if __name__ == "__main__":
    main()

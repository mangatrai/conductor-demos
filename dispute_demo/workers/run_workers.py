"""Start all dispute workers (one polling process per task type).

    python -m workers.run_workers      (from dispute_demo/)
"""

from conductor.client.automator.task_handler import TaskHandler
from conductor.client.configuration.configuration import Configuration

from app.orkes import load_env
import workers.dispute_workers  # noqa: F401  (registers the @worker_task functions)


def main() -> None:
    load_env()
    handler = TaskHandler(configuration=Configuration(), scan_for_annotated_workers=True)
    handler.start_processes()
    print("Dispute workers polling. Ctrl+C to stop.", flush=True)
    try:
        handler.join_processes()
    except KeyboardInterrupt:
        handler.stop_processes()


if __name__ == "__main__":
    main()

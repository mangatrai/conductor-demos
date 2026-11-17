"""Start the whole demo: workers + web app (the dispute console).

    python run.py [--port 8000]      (start.sh does setup first, then runs this)

Workers run in their own process group so Ctrl+C stops every child process.
"""

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--no-workers", action="store_true", help="web app only (run workers elsewhere)")
    args = ap.parse_args()

    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    if not (ROOT / "bank" / "bank.db").exists():
        from bank.seed import seed
        seed()

    workers = None
    if not args.no_workers:
        workers = subprocess.Popen([sys.executable, "-m", "workers.run_workers"], cwd=ROOT,
                                   start_new_session=True)
    try:
        print(f"\n  Dispute console   http://localhost:{args.port}/\n", flush=True)
        uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        if workers and workers.poll() is None:
            os.killpg(workers.pid, signal.SIGTERM)
            try:
                workers.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(workers.pid, signal.SIGKILL)


if __name__ == "__main__":
    main()

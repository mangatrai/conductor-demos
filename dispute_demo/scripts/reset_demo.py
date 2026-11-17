"""Reset the demo: stop in-flight dispute workflows and reseed the bank database.

    python scripts/reset_demo.py            # terminate running disputes + reseed
    python scripts/reset_demo.py --purge    # also delete all dispute executions from Orkes
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.orkes import OrkesError, client  # noqa: E402
from bank.db import set_setting  # noqa: E402
from bank.seed import seed  # noqa: E402


def executions(o, wf_type: str, status: str | None = None) -> list[dict]:
    q = f"workflowType = {wf_type}" + (f" AND status = {status}" if status else "")
    found, start = [], 0
    while True:
        r = o.call("GET", "/workflow/search", params={"start": start, "size": 100, "query": q, "freeText": "*"})
        batch = r.get("results", [])
        found += batch
        if len(batch) < 100:
            return found
        start += 100


def reset(purge: bool = False) -> int:
    """Terminate running dispute workflows (optionally purge them), reseed the bank DB, toggles off."""
    o = client()
    terminated = 0
    for wf_type in ("dispute_intake", "dispute_case"):
        for w in executions(o, wf_type, "RUNNING"):
            try:
                o.terminate_workflow(w["workflowId"], "demo reset")
                terminated += 1
                print(f"terminated {wf_type} {w['workflowId']}")
            except OrkesError as e:
                print(f"could not terminate {w['workflowId']}: {e}")
    if purge:
        for wf_type in ("dispute_intake", "dispute_case"):
            for w in executions(o, wf_type):
                try:
                    o.call("DELETE", f"/workflow/{w['workflowId']}/remove")
                except OrkesError as e:
                    print(f"could not remove {w['workflowId']}: {e}")
        print("purged dispute executions")
    seed()
    set_setting("network_outage", "off")
    set_setting("outage_scope", "all")
    set_setting("worker_bug", "off")
    return terminated


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--purge", action="store_true", help="remove dispute executions from Orkes")
    args = ap.parse_args()
    reset(purge=args.purge)
    print("Demo reset.")


if __name__ == "__main__":
    main()

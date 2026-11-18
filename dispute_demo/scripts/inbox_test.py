"""Orkes only: check that every analyst and ops action in the console also works from the Orkes Task Inbox.

    python run.py                          # in one terminal (Orkes flavor)
    python scripts/inbox_test.py [--base http://localhost:8000]

The Orkes UI submits the whole user form: the read-only case facts (the task's input) plus the
reviewer's choices, through the Human Task API. This test does exactly that, bypassing the console,
and checks both forms' rules: a Partial needs an amount, a Request info needs a question.
Takes about 4 minutes (the ops case waits for the chargeback retries to run out).
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.orkes import OrkesError, client  # noqa: E402
from scripts.smoke_test import Smoke, first_txn, submit  # noqa: E402

TESTER = "inbox-tester"


def inbox_submit(o, task_id: str, choices: dict, **overrides):
    """What the Orkes UI does: claim, then submit the form = task input + the reviewer's choices."""
    task = o.get_human_task(task_id)
    form = {k: v for k, v in task["input"].items() if not k.startswith("__")}
    if task.get("state") != "IN_PROGRESS":  # already claimed by an earlier (rejected) submit
        o.claim_human_task_external(task_id, TESTER)
    return o.call("POST", f"/human/tasks/{task_id}/update", json={**form, **overrides, **choices},
                  params={"complete": "true"})


def rejected(o, task_id: str, choices: dict, expect: str, **overrides) -> str:
    try:
        inbox_submit(o, task_id, choices, **overrides)
    except OrkesError as e:
        return e.body if expect in e.body else f"rejected, but not for '{expect}': {e.body[:200]}"
    return ""


def analyst_scenario(s, o):
    print("1. Analyst works the case in the Orkes inbox: request info, then partial approval")
    s.post("/api/settings", {"networkOutage": False, "merchantAutoReply": False})
    ace = first_txn(s, "CH-1001", "Ace Rapid Plumbing")
    _, (case_id,) = submit(s, "CH-1001", [ace])
    s.wait_stage(case_id, "AWAITING_MERCHANT", 90)
    s.post(f"/api/merchant/cases/{case_id}/respond", {"decision": "CONTEST", "evidence": "Invoice #4471 signed"})
    c = s.wait_stage(case_id, "PENDING_REVIEW", 60)
    task_id = c["live"]["humanTask"]["taskId"]
    form = o.get_human_task(task_id)["input"]
    nulls = [k for k, v in form.items() if v is None]
    s.check(not nulls, f"Form facts have no null values (first round, no cardholder answer yet){': ' + str(nulls) if nulls else ''}")

    err = rejected(o, task_id, {"decision": "APPROVE"}, "null found", cardholderAnswer=None)
    s.check(bool(err) and "null found" in err, "A null fact is still rejected by Orkes (the original bug, reproduced on purpose)")
    err = rejected(o, task_id, {"decision": "REQUEST_INFO"}, "question")
    s.check("question" in err, "Request info without a question is rejected")
    inbox_submit(o, task_id, {"decision": "REQUEST_INFO", "question": "Did the plumber come back to fix the leak?"})
    s.wait_stage(case_id, "AWAITING_CARDHOLDER", 30)
    s.check(True, "Request info with a question accepted; case waits for the cardholder")

    s.post(f"/api/cases/{case_id}/answer", {"answer": "No. A different plumber fixed it for $60."})
    c = s.wait_stage(case_id, "PENDING_REVIEW", 30)
    task_id = c["live"]["humanTask"]["taskId"]
    s.check(o.get_human_task(task_id)["input"].get("cardholderAnswer", "").startswith("No."),
            "Second round: the form shows the cardholder's answer")
    err = rejected(o, task_id, {"decision": "PARTIAL"}, "approvedAmount")
    s.check("approvedAmount" in err, "Partial without an amount is rejected")
    inbox_submit(o, task_id, {"decision": "PARTIAL", "approvedAmount": 40, "note": "Call-out fee stands"})
    c = s.wait_stage(case_id, "RESOLVED", 40)
    s.check(c["live"]["decision"] == "PARTIAL" and c["live"]["approvedAmount"] == 40, "Partial $40 from the inbox closes the case")
    s.check(sum(e["amount"] for e in c["ledger"]) == 40, "Ledger nets to $40")


def ops_scenario(s, o):
    print("2. Ops works the exception in the Orkes inbox: retry filing")
    s.post("/api/settings", {"networkOutage": True, "outageScope": "all", "merchantAutoReply": True})
    tune = first_txn(s, "CH-1003", "TuneWave Music")
    _, (case_id,) = submit(s, "CH-1003", [tune])
    print("   waiting ~2 min for the chargeback retries to run out")
    c = s.wait_stage(case_id, "OPS_EXCEPTION", 240)
    s.post("/api/settings", {"networkOutage": False})
    task_id = c["live"]["opsTask"]["taskId"]
    form = o.get_human_task(task_id)["input"]
    nulls = [k for k, v in form.items() if v is None]
    s.check(not nulls, f"Ops form facts have no null values{': ' + str(nulls) if nulls else ''}")
    inbox_submit(o, task_id, {"decision": "RETRY", "note": "Network is back"})
    c = s.wait_stage(case_id, "RESOLVED", 90)
    s.check(bool(c["live"]["chargebackRef"]) and c["live"]["decision"] == "APPROVE",
            "Ops RETRY from the inbox: chargeback filed, case approved")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    s = Smoke(ap.parse_args().base)
    o = client()
    if o.is_oss:
        sys.exit("Conductor OSS has no Task Inbox or user forms; this test is for Orkes only.")
    s.post("/api/demo/reset", {})
    analyst_scenario(s, o)
    ops_scenario(s, o)
    s.post("/api/settings", {"networkOutage": False, "merchantAutoReply": True})
    print("\nALL PASSED" if not s.failures else f"\n{s.failures} FAILED")
    sys.exit(1 if s.failures else 0)


if __name__ == "__main__":
    main()

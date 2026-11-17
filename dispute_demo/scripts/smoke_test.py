"""End-to-end check of Priya's scenario through the web app API (app + workers must be running).

    python run.py            # in one terminal
    python scripts/smoke_test.py [--base http://localhost:8000]

Flow: network outage on -> dispute 4 charges -> outage off (retries recover) -> merchant
replies -> analyst requests info -> cardholder answers -> partial / approve -> parent closes.
Then: outage outlasting all retries -> ops exception queue -> ops retry / proceed; and a worker
bug that fails a case -> parent keeps waiting -> fix + Retry from the failed step.
"""

import argparse
import sys
import time

import requests

CH = "CH-1001"


class Smoke:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.failures = 0

    def get(self, path):
        r = requests.get(self.base + path, timeout=30)
        r.raise_for_status()
        return r.json()

    def post(self, path, body):
        r = requests.post(self.base + path, json=body, timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"POST {path} -> {r.status_code} {r.text}")
        return r.json()

    def check(self, ok: bool, msg: str):
        print(("  PASS " if ok else "  FAIL ") + msg, flush=True)
        if not ok:
            self.failures += 1

    def case(self, case_id):
        return self.get(f"/api/cases/{case_id}")

    def wait_stage(self, case_id, stages, timeout=150):
        stages = {stages} if isinstance(stages, str) else set(stages)
        t0, last = time.time(), "not opened yet"
        while time.time() - t0 < timeout:
            r = requests.get(f"{self.base}/api/cases/{case_id}", timeout=30)
            if r.status_code == 200:
                c = r.json()
                last = c["live"]["stage"]
                if last in stages:
                    return c
            elif r.status_code != 404:  # 404 = workflow hasn't opened the case yet
                r.raise_for_status()
            time.sleep(1.5)
        raise TimeoutError(f"{case_id} never reached {stages}; last {last}")


def first_txn(s, ch, merchant):
    txns = s.get(f"/api/cardholders/{ch}/transactions")["transactions"]
    return next(t for t in txns if t["merchant_name"] == merchant and not t["outsideWindow"] and not t["caseId"])


def submit(s, ch, txns):
    d = s.post("/api/disputes", {"cardholderId": ch, "items": [
        {"txnId": t["id"], "reasonCode": "CANCELLED", "note": "Cancelled, still billed"} for t in txns]})
    did = d["disputeId"]
    return did, [f"{did.replace('D-', 'DSP-')}-{i}" for i in range(1, len(txns) + 1)]


def parent_status(s, ch, did):
    return next(x for x in s.get(f"/api/cardholders/{ch}/disputes") if x["id"] == did)["workflowStatus"]


def wait_parent(s, ch, did, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if parent_status(s, ch, did) == "COMPLETED":
            return True
        time.sleep(2)
    return False


def ops_exception_scenario(s):
    ch = "CH-1003"
    print("6. Outage outlasts every retry -> cases parked in ops queue (not failed) -> ops retry / proceed")
    s.post("/api/settings", {"networkOutage": True, "merchantAutoReply": True})
    tune, books = first_txn(s, ch, "TuneWave Music"), first_txn(s, ch, "PageTurner Books")
    did, (tune_id, books_id) = submit(s, ch, [tune, books])
    print(f"   dispute {did}; waiting ~2 min for 6 retries with backoff to run out")
    t = s.wait_stage(tune_id, "OPS_EXCEPTION", timeout=240)
    s.wait_stage(books_id, "OPS_EXCEPTION", timeout=60)
    s.check(t["live"]["chargebackFailures"] == 7, f"All 7 chargeback attempts failed ({t['live']['chargebackFailures']})")
    lastErr = (t["live"]["opsTask"] or {}).get("input", {}).get("lastError") or ""
    s.check("503" in lastErr and "${" not in lastErr, f"Ops task shows the network error: {lastErr[:60]}")
    s.check(parent_status(s, ch, did) == "RUNNING", "Parent dispute still open while cases wait for ops")
    s.post("/api/settings", {"networkOutage": False})
    s.post(f"/api/cases/{tune_id}/ops-action", {"decision": "RETRY", "note": "Network incident resolved"})
    s.post(f"/api/cases/{books_id}/ops-action", {"decision": "PROCEED_WITHOUT_CHARGEBACK", "note": "Below write-off limit"})
    t = s.wait_stage(tune_id, "RESOLVED", timeout=90)
    b = s.wait_stage(books_id, "RESOLVED", timeout=60)
    s.check(t["live"]["chargebackRef"] and t["live"]["merchantDecision"] == "ACCEPT" and t["live"]["decision"] == "APPROVE",
            "Ops RETRY: chargeback filed on loop 2, merchant accepted, approved")
    s.check(b["live"]["merchantDecision"] == "NOT_FILED" and b["live"]["decision"] == "APPROVE",
            "Ops PROCEED: no chargeback, low-risk case approved (bank absorbs)")
    s.check(wait_parent(s, ch, did), "Parent dispute COMPLETED after ops resolved both cases")


def worker_bug_scenario(s):
    ch = "CH-1002"
    print("7. Worker bug -> case FAILS loudly -> parent keeps waiting -> fix -> Retry resumes at failed step")
    s.post("/api/settings", {"workerBug": True, "networkOutage": False, "merchantAutoReply": True})
    vault = first_txn(s, ch, "CloudVault Storage")
    did, (case_id,) = submit(s, ch, [vault])
    c = s.wait_stage(case_id, "ERROR", timeout=120)
    s.check((c["live"]["failedTask"] or {}).get("name") == "finalize_case",
            f"Case failed at finalize_case: {(c['live']['failedTask'] or {}).get('reason', '')[:60]}")
    time.sleep(35)  # longer than the parent's 30 s recheck timer
    s.check(parent_status(s, ch, did) == "RUNNING", "Parent still open 35 s after its only case failed")
    s.post("/api/settings", {"workerBug": False})
    s.post(f"/api/cases/{case_id}/retry", {})
    c = s.wait_stage(case_id, "RESOLVED", timeout=60)
    prov = [e for e in c["ledger"] if e["entry_type"] == "PROVISIONAL_CREDIT"]
    s.check(c["live"]["decision"] == "APPROVE" and len(prov) == 1,
            "Retry resumed at finalize_case: approved, provisional credit posted exactly once")
    s.check(any(e["kind"] == "error" for e in c["live"]["timeline"]), "Timeline keeps the failed attempt")
    s.check(wait_parent(s, ch, did, timeout=60), "Parent COMPLETED after the retried case closed")
    msgs = [m for m in s.get(f"/api/cardholders/{ch}/messages") if m["dispute_id"] == did]
    summary = next((m for m in msgs if m["kind"] == "DISPUTE_SUMMARY"), None)
    s.check(summary is not None and f"${vault['amount']:,.2f} of" in summary["body"], "Summary letter counts the retried case")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    s = Smoke(ap.parse_args().base)

    txns = s.get(f"/api/cardholders/{CH}/transactions")["transactions"]
    def pick(merchant, outside=False):
        return next(t for t in txns if t["merchant_name"] == merchant and t["outsideWindow"] == outside and not t["caseId"])
    stream, volt, ace, sky = pick("StreamMax"), pick("VoltCity Electronics"), pick("Ace Rapid Plumbing"), pick("SkyBridge Airlines", True)

    print("1. Network outage ON, merchant auto-reply OFF, submit dispute with 4 charges")
    s.post("/api/settings", {"networkOutage": True, "merchantAutoReply": False})
    d = s.post("/api/disputes", {"cardholderId": CH, "items": [
        {"txnId": stream["id"], "reasonCode": "CANCELLED", "note": "Cancelled in October, still billed"},
        {"txnId": volt["id"], "reasonCode": "NOT_RECEIVED", "note": "TV never arrived"},
        {"txnId": ace["id"], "reasonCode": "NOT_AS_DESCRIBED", "note": "Leak not fixed"},
        {"txnId": sky["id"], "reasonCode": "NOT_AS_DESCRIBED", "note": "Flight was delayed 6 hours"},
    ]})
    did = d["disputeId"]
    ids = {k: f"{did.replace('D-', 'DSP-')}-{i}" for i, k in enumerate(["stream", "volt", "ace", "sky"], start=1)}
    print(f"   dispute {did} -> {d['orkesUrl']}")

    c = s.wait_stage(ids["stream"], "RETRYING", 60)
    s.check(c["live"]["chargebackFailures"] >= 1, f"StreamMax chargeback failing during outage ({c['live']['chargebackFailures']} failures)")
    c = s.wait_stage(ids["sky"], "RESOLVED", 60)
    s.check(c["live"]["route"] == "AUTO_DENY" and c["live"]["decision"] == "REJECT" and not c["ledger"],
            "SkyBridge outside window -> auto-declined, no credit")

    print("2. Network outage OFF -> retries recover")
    time.sleep(4)
    s.post("/api/settings", {"networkOutage": False})
    for k in ("stream", "volt", "ace"):
        c = s.wait_stage(ids[k], "AWAITING_MERCHANT", 150)
        s.check(c["live"]["chargebackRef"] is not None, f"{c['merchant_name']} chargeback filed after {c['live']['chargebackFailures']} failed attempt(s)")

    print("3. Merchant replies")
    s.post(f"/api/merchant/cases/{ids['stream']}/respond", {"decision": "ACCEPT"})
    s.post(f"/api/merchant/cases/{ids['volt']}/respond", {"decision": "CONTEST", "evidence": "Carrier scan: delivered"})
    s.post(f"/api/merchant/cases/{ids['ace']}/respond", {"decision": "CONTEST", "evidence": "Invoice #4471 signed"})
    c = s.wait_stage(ids["stream"], "RESOLVED", 40)
    s.check(c["live"]["decision"] == "APPROVE" and c["live"]["approvedAmount"] == stream["amount"],
            "StreamMax auto-approved in full and finished first")
    queue = [x["id"] for x in s.get("/api/cases?view=queue")]
    s.wait_stage(ids["volt"], "PENDING_REVIEW", 30)
    s.wait_stage(ids["ace"], "PENDING_REVIEW", 30)
    queue = [x["id"] for x in s.get("/api/cases?view=queue")]
    s.check(ids["volt"] in queue and ids["ace"] in queue, "VoltCity and Ace in analyst queue")

    print("4. Analyst requests info on Ace; cardholder answers; analyst partially approves")
    s.post(f"/api/cases/{ids['ace']}/decision", {"decision": "REQUEST_INFO", "question": "Did the plumber come back to fix the leak?"})
    c = s.wait_stage(ids["ace"], "AWAITING_CARDHOLDER", 30)
    s.check(c["live"]["infoRequest"]["question"].startswith("Did the plumber"), "Question visible to cardholder")
    s.post(f"/api/cases/{ids['ace']}/answer", {"answer": "No. A different plumber fixed it for $60."})
    c = s.wait_stage(ids["ace"], "PENDING_REVIEW", 30)
    s.check(c["live"]["humanTask"]["input"].get("cardholderAnswer", "").startswith("No."), "Answer shown in analyst's task")
    s.post(f"/api/cases/{ids['ace']}/decision", {"decision": "PARTIAL", "approvedAmount": 40, "note": "Call-out fee stands"})
    s.post(f"/api/cases/{ids['volt']}/decision", {"decision": "APPROVE", "note": "Delivery photo shows wrong address"})
    ace_c = s.wait_stage(ids["ace"], "RESOLVED", 40)
    volt_c = s.wait_stage(ids["volt"], "RESOLVED", 40)
    s.check(ace_c["live"]["decision"] == "PARTIAL" and ace_c["live"]["approvedAmount"] == 40, "Ace partial $40")
    s.check(sum(e["amount"] for e in ace_c["ledger"]) == 40, "Ace ledger nets to $40 (credit 85, reversal -45)")
    s.check(volt_c["live"]["decision"] == "APPROVE", "VoltCity approved")

    print("5. Parent closes last")
    t0 = time.time()
    while time.time() - t0 < 40:
        dd = next(x for x in s.get(f"/api/cardholders/{CH}/disputes") if x["id"] == did)
        if dd["workflowStatus"] == "COMPLETED":
            break
        time.sleep(1.5)
    s.check(dd["workflowStatus"] == "COMPLETED", "Parent dispute workflow COMPLETED after all cases")
    msgs = [m for m in s.get(f"/api/cardholders/{CH}/messages") if m["dispute_id"] == did]
    summary = next((m for m in msgs if m["kind"] == "DISPUTE_SUMMARY"), None)
    expected = round(stream["amount"] + volt["amount"] + 40, 2)
    s.check(summary is not None and f"${expected:,.2f}" in summary["body"], f"Summary letter credits ${expected:,.2f}")

    ops_exception_scenario(s)
    worker_bug_scenario(s)

    s.post("/api/settings", {"networkOutage": False, "merchantAutoReply": True, "workerBug": False})
    print(f"\n{'ALL PASSED' if not s.failures else str(s.failures) + ' FAILURE(S)'}")
    sys.exit(1 if s.failures else 0)


if __name__ == "__main__":
    main()

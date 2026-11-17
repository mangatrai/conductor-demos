"""Live case state, derived from the Orkes execution (no status-syncing code needed).

The bank DB holds money and case records; *where a case is* comes straight from the
dispute_case workflow execution: current task, retries, merchant reply, analyst decisions.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from app.orkes import client

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()
TTL = 1.5
TERMINAL = {"COMPLETED", "FAILED", "TERMINATED", "TIMED_OUT"}

ROUTE_LABEL = {"AUTO_APPROVE": "Auto-approve", "HUMAN_REVIEW": "Analyst review", "AUTO_DENY": "Auto-decline"}
DECISION_LABEL = {"APPROVE": "Approved", "PARTIAL": "Partially approved", "REJECT": "Declined",
                  "REQUEST_INFO": "More info requested"}
MERCHANT_LABEL = {"ACCEPT": "Merchant accepted the chargeback", "CONTEST": "Merchant contested",
                  "NO_RESPONSE": "Merchant did not respond by the deadline",
                  "NOT_FILED": "No chargeback filed (network down; bank absorbs)"}
OPS_LABEL = {"RETRY": "Ops: retry filing now", "PROCEED_WITHOUT_CHARGEBACK": "Ops: proceed without a chargeback"}
FAILED = ("FAILED", "FAILED_WITH_TERMINAL_ERROR", "TIMED_OUT")


def get_workflow_cached(workflow_id: str) -> dict:
    now = time.time()
    with _lock:
        hit = _cache.get(workflow_id)
        if hit and (hit[1].get("status") in TERMINAL or now - hit[0] < TTL):
            return hit[1]
    wf = client().get_workflow(workflow_id)
    with _lock:
        _cache[workflow_id] = (now, wf)
    return wf


def invalidate(workflow_id: str) -> None:
    with _lock:
        _cache.pop(workflow_id, None)


def _iso(ms: int | None) -> str | None:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _base(ref: str) -> str:
    return ref.split("__")[0]


def money(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def live_state(workflow_id: str) -> dict:
    """Summarise a dispute_case execution for the UI."""
    wf = get_workflow_cached(workflow_id)
    tasks = sorted(wf.get("tasks", []), key=lambda t: t.get("seq", 0))
    by_ref = {t["referenceTaskName"]: t for t in tasks}
    out: dict = {
        "workflowId": workflow_id,
        "workflowStatus": wf["status"],
        "orkesUrl": f"{client().ui_base}/execution/{workflow_id}",
        "route": None, "routeReason": None, "merchantDecision": None, "merchantEvidence": None,
        "chargebackRef": None, "chargebackFailures": 0, "lastError": None,
        "humanTask": None, "infoRequest": None, "merchantWait": None, "conversation": [],
        "provisionalCredit": None, "decision": None, "approvedAmount": None, "decidedBy": None,
        "decisionNote": None, "opsTask": None, "failedTask": None, "retriedSteps": 0,
    }
    events: list[dict] = []

    def ev(t, title, detail="", kind="done", actor="system", internal=False, at=None):
        events.append({"at": at or _iso(t.get("endTime") or t.get("startTime") or t.get("scheduledTime")),
                       "title": title, "detail": detail, "kind": kind, "actor": actor,
                       "internal": internal})

    current = None
    for t in tasks:
        ref, base, st = t["referenceTaskName"], _base(t["referenceTaskName"]), t["status"]
        o = t.get("outputData") or {}
        i = t.get("inputData") or {}
        if st in ("IN_PROGRESS", "SCHEDULED") and t["taskType"] not in ("DO_WHILE", "SUB_WORKFLOW"):
            current = t
        if base == "open_case" and st == "COMPLETED":
            ev(t, "Case opened", f"Resolve by {o.get('deadline')} (Reg Z)")
        elif base == "enrich_case" and st == "COMPLETED":
            ev(t, "Charge verified", f"{o.get('merchantName')} · {o.get('mccDescription')} · MCC {o.get('mcc')}",
               internal=False)
        elif base == "triage_rules" and st == "COMPLETED":
            r = o.get("result") or {}
            out["route"], out["routeReason"] = r.get("route"), r.get("reason")
            ev(t, f"Triage: {ROUTE_LABEL.get(r.get('route'), r.get('route'))}", r.get("reason", ""),
               actor="rules")
        elif base == "issue_provisional_credit" and st == "COMPLETED":
            out["provisionalCredit"] = o.get("creditedAmount")
            ev(t, f"Provisional credit {money(o.get('creditedAmount'))}", "Posted to your account while we investigate")
        elif base == "file_chargeback":
            if st in FAILED or st == "COMPLETED_WITH_ERRORS":
                out["chargebackFailures"] += 1
                out["lastError"] = t.get("reasonForIncompletion")
                ev(t, f"Card network attempt {t.get('retryCount', 0) + 1} failed",
                   f"{t.get('reasonForIncompletion')}", kind="warn", internal=True)
            elif st == "COMPLETED":
                out["chargebackRef"] = o.get("chargebackRef")
                ev(t, "Chargeback sent to merchant", f"Ref {o.get('chargebackRef')} via {o.get('network')}")
        elif base == "chargeback_exception":
            waiting = st in ("IN_PROGRESS", "SCHEDULED")
            ev(t, "Escalated to operations", "Card network still down after every automatic retry. "
               "Case is parked (not failed) until ops acts.", kind="action" if waiting else "warn",
               actor="operations", internal=True, at=_iso(t.get("startTime")))
            if waiting:
                out["opsTask"] = {"taskId": t["taskId"], "taskRef": ref, "since": _iso(t.get("startTime")),
                                  "iteration": t.get("iteration", 1),
                                  "input": {k: v for k, v in i.items() if not k.startswith("__")}}
            elif st == "COMPLETED":
                ev(t, OPS_LABEL.get(o.get("decision"), o.get("decision")), o.get("note") or "",
                   actor="operations", internal=True)
        elif base == "await_merchant_response":
            if st == "IN_PROGRESS":
                deadline = (t.get("startTime") or 0) + int(t.get("callbackAfterSeconds") or 0) * 1000
                out["merchantWait"] = {"since": _iso(t.get("startTime")), "deadline": _iso(deadline),
                                       "taskRef": ref}
                ev(t, "Waiting for merchant response", "Merchant can accept or contest",
                   kind="wait", actor="merchant", at=_iso(t.get("startTime")))
        elif base == "merchant_outcome" and st == "COMPLETED":
            r = o.get("result") or {}
            out["merchantDecision"], out["merchantEvidence"] = r.get("merchantDecision"), r.get("merchantEvidence")
            ev(t, MERCHANT_LABEL.get(r.get("merchantDecision"), r.get("merchantDecision")),
               r.get("merchantEvidence") or "", actor="merchant",
               kind="warn" if r.get("merchantDecision") == "CONTEST" else "done")
        elif base == "analyst_review":
            if st in ("IN_PROGRESS", "SCHEDULED"):
                out["humanTask"] = {"taskId": t["taskId"], "taskRef": ref, "iteration": t.get("iteration", 1),
                                    "since": _iso(t.get("startTime")),
                                    "input": {k: v for k, v in i.items() if not k.startswith("__")}}
                ev(t, "With a dispute analyst", "Reviewing your claim and the merchant's evidence",
                   kind="wait", actor="analyst", at=_iso(t.get("startTime")))
            elif st == "COMPLETED":
                d = o.get("decision")
                if d == "REQUEST_INFO":
                    out["conversation"].append({"at": _iso(t.get("endTime")), "from": "analyst",
                                                "text": o.get("question")})
                    ev(t, "Analyst requested more information", o.get("question", ""), actor="analyst")
                else:
                    detail = o.get("note") or ""
                    ev(t, f"Analyst decision: {DECISION_LABEL.get(d, d)}", detail, actor="analyst")
        elif base == "await_cardholder_info":
            if st == "IN_PROGRESS":
                out["infoRequest"] = {"question": i.get("question"), "taskRef": ref,
                                      "since": _iso(t.get("startTime"))}
                ev(t, "Waiting for the cardholder's answer", i.get("question", ""), kind="action", actor="cardholder",
                   at=_iso(t.get("startTime")))
            elif st == "COMPLETED":
                out["conversation"].append({"at": _iso(t.get("endTime")), "from": "cardholder",
                                            "text": o.get("answer")})
                ev(t, "Cardholder answered", o.get("answer", ""), actor="cardholder")
        elif base == "finalize_case" and st in FAILED:
            out["retriedSteps"] += 1
            ev(t, "Step failed: posting the final ledger entries", t.get("reasonForIncompletion") or "",
               kind="error", internal=True)
        elif base == "finalize_case" and st == "COMPLETED":
            out.update(decision=o.get("decision"), approvedAmount=o.get("approvedAmount"))
            ev(t, "Case resolved", o.get("outcome", ""), kind="final")
        elif base in ("set_rules_decision", "set_auto_decision", "set_analyst_decision") and st == "COMPLETED":
            out["decidedBy"] = i.get("decidedBy")
            out["decisionNote"] = i.get("note")

    if wf["status"] in ("FAILED", "TIMED_OUT"):
        bad = next((t for t in reversed(tasks) if t["status"] in FAILED
                    and t["taskType"] not in ("DO_WHILE", "SUB_WORKFLOW")), None)
        if bad:
            out["failedTask"] = {"ref": bad["referenceTaskName"], "name": bad.get("taskDefName"),
                                 "reason": bad.get("reasonForIncompletion") or wf.get("reasonForIncompletion"),
                                 "at": _iso(bad.get("endTime"))}
    stage, label, waiting_on = _stage(wf, current, out)
    out["steps"], out["analystRounds"] = _steps(tasks, out, stage)
    out.update(stage=stage, stageLabel=label, waitingOn=waiting_on, timeline=events,
               startTime=_iso(wf.get("startTime")), endTime=_iso(wf.get("endTime")),
               output=wf.get("output") or {})
    return out


def _steps(tasks: list[dict], s: dict, stage: str) -> tuple[dict, int]:
    """Six business steps for the console's progress chips: todo/active/done/warn/wait/error/skip."""
    last: dict[str, dict] = {}
    rounds = 0
    for t in tasks:  # sorted by seq, so the latest iteration of a looped task wins
        b = _base(t["referenceTaskName"])
        last[b] = t
        rounds += b == "analyst_review"
    st = lambda b: (last.get(b) or {}).get("status")  # noqa: E731
    live = ("SCHEDULED", "IN_PROGRESS")
    denied = s.get("route") == "AUTO_DENY"
    steps = {k: "todo" for k in ("rules", "credit", "chargeback", "merchant", "review", "resolve")}
    steps["rules"] = "done" if st("triage_rules") == "COMPLETED" else "active"
    if denied:
        steps.update(credit="skip", chargeback="skip", merchant="skip", review="skip")
    else:
        if st("issue_provisional_credit") == "COMPLETED":
            steps["credit"] = "done"
        elif st("issue_provisional_credit") in live:
            steps["credit"] = "active"
        if s.get("chargebackRef"):
            steps["chargeback"] = "done"
        elif s.get("opsTask"):
            steps["chargeback"] = "wait"
        elif s.get("merchantDecision") == "NOT_FILED":
            steps["chargeback"] = "skip"
        elif s.get("chargebackFailures"):
            steps["chargeback"] = "warn"
        elif st("file_chargeback") in live:
            steps["chargeback"] = "active"
        md = s.get("merchantDecision")
        if s.get("merchantWait"):
            steps["merchant"] = "active"
        elif md == "CONTEST":
            steps["merchant"] = "warn"
        elif md == "NOT_FILED":
            steps["merchant"] = "skip"
        elif md:
            steps["merchant"] = "done"
        if s.get("humanTask") or s.get("infoRequest"):
            steps["review"] = "wait"
        elif st("set_analyst_decision") == "COMPLETED":
            steps["review"] = "done"
        elif st("set_auto_decision") == "COMPLETED":
            steps["review"] = "skip"
    if st("finalize_case") == "COMPLETED":
        steps["resolve"] = "done"
    elif stage == "ERROR":
        steps["resolve"] = "error"
    elif st("finalize_case") in live or stage == "RESOLVING":
        steps["resolve"] = "active"
    return steps, rounds


def _stage(wf: dict, current: dict | None, s: dict) -> tuple[str, str, str]:
    status = wf["status"]
    if status == "COMPLETED":
        return "RESOLVED", DECISION_LABEL.get(s.get("decision"), "Resolved"), ""
    if status in ("FAILED", "TIMED_OUT"):
        step = (s.get("failedTask") or {}).get("name") or "a step"
        return "ERROR", f"Failed at {step}", "operations"
    if status == "TERMINATED":
        return "CANCELLED", "Cancelled", ""
    if status == "PAUSED":
        return "PAUSED", "Paused", "operations"
    base = _base(current["referenceTaskName"]) if current else ""
    if base == "file_chargeback" and s["chargebackFailures"]:
        return "RETRYING", f"Card network retrying ({s['chargebackFailures']} failed)", "system"
    if base == "chargeback_exception":
        return "OPS_EXCEPTION", "Ops: chargeback not filed", "operations"
    if base == "await_merchant_response":
        return "AWAITING_MERCHANT", "Awaiting merchant", "merchant"
    if base == "analyst_review":
        return "PENDING_REVIEW", "Pending analyst review", "analyst"
    if base == "await_cardholder_info":
        return "AWAITING_CARDHOLDER", "Waiting on cardholder", "cardholder"
    if base in ("finalize_case", "notify_case_resolved"):
        return "RESOLVING", "Resolving", "system"
    return "PROCESSING", "Processing", "system"

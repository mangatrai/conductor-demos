"""Web app: the one-screen dispute console (/) and the JSON API behind it.

    uvicorn app.main:app --port 8000      (from dispute_demo/)  or  python run.py
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import cases as live
from app import merchant_sim
from app.orkes import OrkesError, client
from bank import db
from bank.db import REASONS, connect, row, rows

STATIC = Path(__file__).resolve().parent / "static"
ANALYST_ID = "alex.morgan@bank-demo.test"
OPS_ID = "ops.desk@bank-demo.test"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    stop = merchant_sim.start_background()
    yield
    stop.set()


app = FastAPI(title="Dispute demo", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
@app.get("/console")
def console_page():
    return FileResponse(STATIC / "console.html")


# ------------------------------------------------------------------ helpers
def _case_rows(where: str = "", *args) -> list[dict]:
    with connect() as c:
        return rows(c, f"""
            SELECT cs.*, ch.name AS cardholder_name, m.name AS merchant_name, m.category,
                   m.mcc_description, m.sim_behaviour, t.posted_date, t.description AS txn_description
            FROM cases cs
            JOIN cardholders ch ON ch.id = cs.cardholder_id
            JOIN transactions t ON t.id = cs.txn_id
            JOIN merchants m ON m.id = t.merchant_id
            WHERE cs.historical = 0 {where}
            ORDER BY cs.opened_at DESC, cs.id""", *args)


def _with_live(case: dict, full: bool = False) -> dict:
    case = dict(case)
    case["reasonLabel"] = REASONS.get(case.get("reason_code"), case.get("reason_code"))
    if not case.get("workflow_id"):
        case["live"] = {"stage": "PROCESSING", "stageLabel": "Opening", "timeline": []}
        return case
    try:
        st = live.live_state(case["workflow_id"])
    except OrkesError as e:
        st = {"stage": "UNKNOWN", "stageLabel": "Unavailable", "error": str(e), "timeline": []}
    if not full:
        st = {k: v for k, v in st.items() if k not in ("output",)}
    case["live"] = st
    return case


def _get_case(case_id: str) -> dict:
    found = _case_rows("AND cs.id = ?", case_id)
    if not found:
        raise HTTPException(404, f"Unknown case {case_id}")
    return found[0]


# ------------------------------------------------------------------ cardholder
@app.get("/api/cardholders")
def cardholders():
    with connect() as c:
        return rows(c, "SELECT id, name, email, card_last4, card_status, credit_limit, persona FROM cardholders")


@app.get("/api/cardholders/{cid}/transactions")
def transactions(cid: str):
    with connect() as c:
        txns = rows(c, """
            SELECT t.*, m.name AS merchant_name, m.category, m.mcc, m.mcc_description, m.city
            FROM transactions t JOIN merchants m ON m.id = t.merchant_id
            WHERE t.cardholder_id = ? ORDER BY t.posted_date DESC, t.id DESC""", cid)
        open_cases = {r["txn_id"]: r for r in rows(c, """
            SELECT txn_id, id, closed_at, decision FROM cases
            WHERE cardholder_id = ? AND historical = 0""", cid)}
        ledger = rows(c, "SELECT * FROM ledger_entries WHERE cardholder_id=? ORDER BY id", cid)
    for t in txns:
        t["outsideWindow"] = db.outside_window(t["statement_date"])
        case = open_cases.get(t["id"])
        t["caseId"] = case["id"] if case else None
        t["caseClosed"] = bool(case and case["closed_at"])
        t["caseDecision"] = case["decision"] if case else None
    balance = round(sum(t["amount"] for t in txns) + sum(e["amount"] * -1 for e in ledger), 2)
    return {"transactions": txns, "ledger": ledger, "balance": balance}


class DisputeItem(BaseModel):
    txnId: str
    reasonCode: str
    note: str = ""


class DisputeRequest(BaseModel):
    cardholderId: str
    items: list[DisputeItem] = Field(min_length=1)


@app.post("/api/disputes")
def create_dispute(req: DisputeRequest):
    with connect() as c:
        taken = {r["txn_id"] for r in rows(c, "SELECT txn_id FROM cases WHERE historical=0")}
        dup = [i.txnId for i in req.items if i.txnId in taken]
        if dup:
            raise HTTPException(409, f"Already disputed: {', '.join(dup)}")
        last = row(c, "SELECT MAX(CAST(SUBSTR(id, 3) AS INTEGER)) AS n FROM disputes")
        dispute_id = f"D-{(last['n'] or 1000) + 1}"
        c.execute("INSERT INTO disputes(id, cardholder_id, created_at, item_count) VALUES(?,?,?,?)",
                  (dispute_id, req.cardholderId, db.now_iso(), len(req.items)))
    wf_input = {"disputeId": dispute_id, "cardholderId": req.cardholderId, "channel": "web",
                "items": [i.model_dump() for i in req.items]}
    workflow_id = client().start_workflow("dispute_intake", wf_input, correlation_id=dispute_id)
    with connect() as c:
        c.execute("UPDATE disputes SET workflow_id=? WHERE id=?", (workflow_id, dispute_id))
    return {"disputeId": dispute_id, "workflowId": workflow_id,
            "orkesUrl": f"{client().ui_base}/execution/{workflow_id}"}


@app.get("/api/cardholders/{cid}/disputes")
def cardholder_disputes(cid: str):
    with connect() as c:
        disputes = rows(c, "SELECT * FROM disputes WHERE cardholder_id=? ORDER BY created_at DESC", cid)
    case_rows = _case_rows("AND cs.cardholder_id = ?", cid)
    out = []
    for d in disputes:
        cs = sorted([_with_live(x) for x in case_rows if x["dispute_id"] == d["id"]], key=lambda x: x["id"])
        for x in cs:  # cardholders don't see internal retry noise
            x["live"]["timeline"] = [e for e in x["live"].get("timeline", []) if not e.get("internal")]
        parent_status = None
        if d.get("workflow_id"):
            try:
                parent_status = live.get_workflow_cached(d["workflow_id"])["status"]
            except OrkesError:
                parent_status = "UNKNOWN"
        d.update(cases=cs, workflowStatus=parent_status,
                 resolvedCount=sum(1 for x in cs if x["live"].get("stage") == "RESOLVED"),
                 orkesUrl=f"{client().ui_base}/execution/{d['workflow_id']}" if d.get("workflow_id") else None)
        out.append(d)
    return out


@app.get("/api/cardholders/{cid}/messages")
def messages(cid: str):
    with connect() as c:
        return rows(c, "SELECT * FROM messages WHERE cardholder_id=? ORDER BY id DESC", cid)


class Answer(BaseModel):
    answer: str = Field(min_length=1)


@app.post("/api/cases/{case_id}/answer")
def answer_info_request(case_id: str, body: Answer):
    case = _get_case(case_id)
    st = live.live_state(case["workflow_id"])
    req = st.get("infoRequest")
    if not req:
        raise HTTPException(409, "No open question on this case")
    client().complete_task_by_ref(case["workflow_id"], req["taskRef"],
                                  {"answer": body.answer, "answeredAt": db.now_iso()})
    live.invalidate(case["workflow_id"])
    return {"ok": True}


# ------------------------------------------------------------------ analyst
@app.get("/api/cases")
def list_cases(view: str = "all"):
    out = [_with_live(c) for c in _case_rows()]
    for c in out:
        c["live"].pop("timeline", None)
    if view == "queue":
        out = [c for c in out if c["live"].get("stage") == "PENDING_REVIEW"]
        out.sort(key=lambda c: c["live"].get("humanTask", {}).get("since") or "")
    return out


@app.get("/api/cases/{case_id}")
def case_detail(case_id: str):
    case = _with_live(_get_case(case_id), full=True)
    with connect() as c:
        case["ledger"] = rows(c, "SELECT * FROM ledger_entries WHERE case_id=? ORDER BY id", case_id)
        case["history"] = rows(c, """SELECT id, opened_at, amount, decision FROM cases
                                     WHERE cardholder_id=? AND dispute_id != ? ORDER BY opened_at DESC""",
                               case["cardholder_id"], case["dispute_id"])
    return case


class Decision(BaseModel):
    decision: str
    approvedAmount: float | None = None
    note: str = ""
    question: str = ""


@app.post("/api/cases/{case_id}/decision")
def decide(case_id: str, body: Decision):
    if body.decision not in ("APPROVE", "PARTIAL", "REJECT", "REQUEST_INFO"):
        raise HTTPException(400, "decision must be APPROVE, PARTIAL, REJECT or REQUEST_INFO")
    case = _get_case(case_id)
    if body.decision == "PARTIAL" and (body.approvedAmount is None or not 0 < body.approvedAmount < case["amount"]):
        raise HTTPException(400, f"Partial amount must be between 0 and {case['amount']}")
    if body.decision == "REQUEST_INFO" and not body.question.strip():
        raise HTTPException(400, "Add the question for the cardholder")
    st = live.live_state(case["workflow_id"])
    ht = st.get("humanTask")
    if not ht:
        raise HTTPException(409, "This case is not waiting for an analyst")
    o = client()
    o.claim_human_task_external(ht["taskId"], ANALYST_ID)
    # Orkes validates the output against the form's JSON schema, so omit fields that don't apply
    output = {"decision": body.decision, "note": body.note, "analyst": ANALYST_ID}
    if body.decision == "PARTIAL":
        output["approvedAmount"] = body.approvedAmount
    if body.decision == "REQUEST_INFO":
        output["question"] = body.question
    o.complete_human_task(ht["taskId"], output)
    live.invalidate(case["workflow_id"])
    return {"ok": True}


class OpsAction(BaseModel):
    decision: str
    note: str = ""


@app.post("/api/cases/{case_id}/ops-action")
def ops_action(case_id: str, body: OpsAction):
    """Complete the ops exception Human task: retry filing now, or proceed without a chargeback."""
    if body.decision not in ("RETRY", "PROCEED_WITHOUT_CHARGEBACK"):
        raise HTTPException(400, "decision must be RETRY or PROCEED_WITHOUT_CHARGEBACK")
    case = _get_case(case_id)
    st = live.live_state(case["workflow_id"])
    task = st.get("opsTask")
    if not task:
        raise HTTPException(409, "This case is not waiting for ops")
    o = client()
    o.claim_human_task_external(task["taskId"], OPS_ID)
    o.complete_human_task(task["taskId"], {"decision": body.decision, "note": body.note})
    live.invalidate(case["workflow_id"])
    return {"ok": True}


@app.post("/api/cases/{case_id}/retry")
def retry_case(case_id: str):
    """Orkes 'Retry': resume the failed case workflow from the failed step. Completed steps are not re-run."""
    case = _get_case(case_id)
    wf = live.get_workflow_cached(case["workflow_id"])
    if wf["status"] not in ("FAILED", "TIMED_OUT"):
        raise HTTPException(409, f"Case workflow is {wf['status']}, nothing to retry")
    client().call("POST", f"/workflow/{case['workflow_id']}/retry")
    live.invalidate(case["workflow_id"])
    return {"ok": True}


@app.get("/api/search")
def search(q: str):
    """Orkes workflow search: correlation ID + free text over workflow input/output."""
    res = client().search_workflows(free_text=q.strip() or "*", size=50)
    items = []
    for r in res.get("results", []):
        if r.get("workflowType") not in ("dispute_intake", "dispute_case"):
            continue
        # search summaries carry input as a Java Map string: "{caseId=DSP-1-1, merchantName=..., ...}"
        raw = r.get("input") or ""
        fields = {k: (m.group(1).strip() if (m := re.search(rf"(?:^|[{{,]\s*){k}=([^,}}]+)", raw)) else None)
                  for k in ("caseId", "disputeId", "merchantName", "cardholderId", "cardholderName")}
        items.append({"workflowId": r["workflowId"], "workflowType": r["workflowType"],
                      "status": r["status"], "correlationId": r.get("correlationId"),
                      "startTime": r.get("startTime"), "input": fields,
                      "orkesUrl": f"{client().ui_base}/execution/{r['workflowId']}"})
    return {"query": q, "totalHits": res.get("totalHits"), "results": items}


# ------------------------------------------------------------------ merchant simulator
@app.get("/api/merchant/cases")
def merchant_cases():
    out = []
    for c in merchant_sim.open_case_rows():
        st = live.live_state(c["workflow_id"])
        if st.get("merchantWait") or st.get("stage") in ("RETRYING", "OPS_EXCEPTION"):
            out.append({"caseId": c["id"], "merchant": c["merchant_name"], "amount": c["amount"],
                        "profile": c["sim_behaviour"], "cardholder": c["cardholder_name"],
                        "reasonLabel": REASONS.get(c["reason_code"], c["reason_code"]),
                        "chargebackRef": st.get("chargebackRef"), "stage": st.get("stage"),
                        "stageLabel": st.get("stageLabel"), "wait": st.get("merchantWait"),
                        "failures": st.get("chargebackFailures"), "lastError": st.get("lastError"),
                        "evidence": c.get("contest_evidence") or "", "orkesUrl": st.get("orkesUrl")})
    return {"cases": out, "autoReplySeconds": merchant_sim.AUTO_REPLY_SECONDS,
            "settings": settings()}


class MerchantReply(BaseModel):
    decision: str
    evidence: str = ""


@app.post("/api/merchant/cases/{case_id}/respond")
def merchant_respond(case_id: str, body: MerchantReply):
    if body.decision not in ("ACCEPT", "CONTEST"):
        raise HTTPException(400, "decision must be ACCEPT or CONTEST")
    case = next((c for c in merchant_sim.open_case_rows() if c["id"] == case_id), None)
    if not case:
        raise HTTPException(404, "Case not open")
    try:
        merchant_sim.respond(case, body.decision, body.evidence, source="simulator")
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


@app.get("/api/settings")
def settings():
    return {"networkOutage": db.get_setting("network_outage", "off") == "on",
            "outageScope": db.get_setting("outage_scope", "all"),
            "merchantAutoReply": db.get_setting("merchant_auto_reply", "on") == "on",
            "workerBug": db.get_setting("worker_bug", "off") == "on"}


class SettingsBody(BaseModel):
    networkOutage: bool | None = None
    outageScope: str | None = None  # "all" (every chargeback fails) or one merchant's name, e.g. "VoltCity Electronics"
    merchantAutoReply: bool | None = None
    workerBug: bool | None = None


@app.post("/api/settings")
def update_settings(body: SettingsBody):
    if body.outageScope is not None:
        if not body.outageScope.strip():
            raise HTTPException(400, "outageScope must be 'all' or a merchant name")
        db.set_setting("outage_scope", body.outageScope)
    if body.networkOutage is not None:
        db.set_setting("network_outage", "on" if body.networkOutage else "off")
    if body.merchantAutoReply is not None:
        db.set_setting("merchant_auto_reply", "on" if body.merchantAutoReply else "off")
    if body.workerBug is not None:
        db.set_setting("worker_bug", "on" if body.workerBug else "off")
    return settings()


# ------------------------------------------------------------------ one-screen console
@app.get("/api/console")
def console_state(cardholderId: str = "CH-1001"):
    """Everything the console shows, in one poll: the cardholder's latest dispute, its cases with live
    Orkes state (internal events included), the parent workflow, letters and the demo toggles."""
    with connect() as c:
        d = row(c, "SELECT * FROM disputes WHERE cardholder_id=? ORDER BY created_at DESC, id DESC LIMIT 1",
                cardholderId)
        letters = rows(c, "SELECT * FROM messages WHERE cardholder_id=? AND dispute_id=? ORDER BY id DESC",
                       cardholderId, d["id"]) if d else []
    out = {"settings": settings(), "orkesUi": client().ui_base, "dispute": None}
    if not d:
        return out
    cases = sorted((_with_live(x) for x in _case_rows("AND cs.dispute_id = ?", d["id"])), key=lambda x: x["id"])
    parent = {"status": None, "startTime": None, "endTime": None}
    if d.get("workflow_id"):
        try:
            wf = live.get_workflow_cached(d["workflow_id"])
            parent = {"status": wf["status"], "startTime": wf.get("startTime"), "endTime": wf.get("endTime")}
        except OrkesError as e:
            parent = {"status": "UNKNOWN", "error": str(e)}
    out["dispute"] = {**d, "parent": parent, "cases": cases, "letters": letters,
                      "orkesUrl": f"{client().ui_base}/execution/{d['workflow_id']}" if d.get("workflow_id") else None}
    return out


@app.post("/api/demo/reset")
def demo_reset():
    """Same as scripts/reset_demo.py: terminate running dispute workflows, reseed the bank, toggles off."""
    from scripts.reset_demo import reset
    terminated = reset(purge=False)
    live._cache.clear()
    return {"ok": True, "terminated": terminated}


@app.get("/api/meta")
def meta():
    return {"orkesUi": client().ui_base, "reasons": REASONS, "analyst": ANALYST_ID,
            "now": datetime.now(timezone.utc).isoformat()}

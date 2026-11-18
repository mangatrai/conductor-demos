"""Workers for the credit card dispute demo.

Each @worker_task function is one 'box' in the workflow diagram that calls a bank system
(here: the SQLite core-banking mock). Same pattern as labs/sanctions_worker.py.
Raising an exception fails the attempt; Conductor retries per the task definition.
"""


import uuid
from datetime import datetime, timedelta, timezone

from conductor.client.context import get_task_context
from conductor.client.worker.exception import NonRetryableException
from conductor.client.worker.worker_task import worker_task

from bank import db
from bank.db import REASONS, connect, now_iso, row, transaction_view


def log(msg: str) -> None:
    """Shows up in the task's Logs tab in the Orkes UI."""
    try:
        get_task_context().add_log(msg)
    except Exception:
        pass
    print(msg, flush=True)


def money(v: float) -> str:
    return f"${v:,.2f}"


# --------------------------------------------------------------------------- parent
@worker_task(task_definition_name="validate_cardholder")
def validate_cardholder(cardholderId: str) -> dict:
    with connect() as c:
        ch = row(c, "SELECT * FROM cardholders WHERE id=?", cardholderId)
    if not ch:
        raise NonRetryableException(f"Unknown cardholder {cardholderId}")
    log(f"Cardholder {ch['name']} card ****{ch['card_last4']} status {ch['card_status']}")
    return {"status": ch["card_status"], "name": ch["name"], "email": ch["email"],
            "cardLast4": ch["card_last4"]}


def case_input(c, caseId: str, disputeId: str, cardholderId: str, txnId: str, reasonCode: str,
               note: str) -> dict:
    """Input of one dispute_case workflow (same for the first charges and for charges added later)."""
    holder = row(c, "SELECT name FROM cardholders WHERE id=?", cardholderId)
    txn = transaction_view(c, txnId)
    if not txn or txn["cardholder_id"] != cardholderId:
        raise NonRetryableException(f"Transaction {txnId} not found for {cardholderId}")
    reasonCode = reasonCode or "NOT_RECEIVED"
    return {
        "caseId": caseId,
        "disputeId": disputeId,
        "cardholderId": cardholderId,
        "cardholderName": holder["name"] if holder else "",
        "txnId": txnId,
        "reasonCode": reasonCode,
        "reasonLabel": REASONS.get(reasonCode, reasonCode),
        "cardholderNote": note or "",
        "merchantName": txn["merchant_name"],
        "amount": txn["amount"],
    }


def case_id(disputeId: str, n: int) -> str:
    return f"{disputeId.replace('D-', 'DSP-')}-{n}"


@worker_task(task_definition_name="prepare_cases")
def prepare_cases(disputeId: str, cardholderId: str, items: object) -> dict:
    """One case per disputed charge. Output feeds the dynamic fork."""
    with connect() as c:
        cases = [case_input(c, case_id(disputeId, i), disputeId, cardholderId, item["txnId"],
                            item.get("reasonCode", "NOT_RECEIVED"), item.get("note", ""))
                 for i, item in enumerate(items, start=1)]
    total = round(sum(x["amount"] for x in cases), 2)
    log(f"Dispute {disputeId}: {len(cases)} charge(s), total {money(total)}")
    return {"cases": cases, "caseCount": len(cases), "totalDisputed": total}


@worker_task(task_definition_name="collect_case_results")
def collect_case_results(disputeId: str, expectedCount: object = 0, handoverToken: str = "") -> dict:
    """Ask the case system which cases of this dispute are closed, and hand over a charge added since.

    The dispute's cases are the first `expectedCount` charges plus every charge added later. While any is
    open the parent keeps waiting. When all are closed, the dispute is marked CLOSING in the same locked
    step, so a charge can't be added between this check and the parent closing (the app refuses it).

    An added charge is handed to the parent (which starts its case) exactly once. handoverToken is the
    parent's id + loop iteration: a retry of this same task gets the same charge back, in case the first
    answer was lost; a later iteration never does. (Conductor OSS ignores START_WORKFLOW idempotency keys,
    so duplicates are prevented here.)"""
    expected = int(expectedCount or 0)
    with connect(immediate=True) as c:
        rows_ = db.rows(c, """SELECT cs.id, cs.amount, cs.decision, cs.approved_amount, cs.decided_by, cs.closed_at,
                                  m.name AS merchant_name
                           FROM cases cs JOIN transactions t ON t.id = cs.txn_id JOIN merchants m ON m.id = t.merchant_id
                           WHERE cs.dispute_id = ? ORDER BY cs.id""", disputeId)
        added = db.rows(c, "SELECT * FROM added_charges WHERE dispute_id=? ORDER BY requested_at, case_id", disputeId)
        closed = [r for r in rows_ if r["closed_at"]]
        closed_ids = {r["id"] for r in closed}
        all_ids = [case_id(disputeId, i) for i in range(1, expected + 1)] + [a["case_id"] for a in added]
        all_ids += [r["id"] for r in rows_ if r["id"] not in all_ids]
        open_ids = [i for i in all_ids if i not in closed_ids]
        pending = len(open_ids)

        new_case = None
        mine = [a for a in added if handoverToken and a["handover_token"] == handoverToken]
        todo = mine or [a for a in added if not a["handover_token"]]
        if todo:
            a = todo[0]
            new_case = case_input(c, a["case_id"], disputeId, a["cardholder_id"], a["txn_id"],
                                  a["reason_code"], a["note"])
            c.execute("UPDATE added_charges SET handover_token=?, started_at=? WHERE case_id=?",
                      (handoverToken or "-", now_iso(), a["case_id"]))
        if not pending:
            c.execute("UPDATE disputes SET status='CLOSING' WHERE id=?", (disputeId,))
    cases = [{"caseId": r["id"], "merchantName": r["merchant_name"], "amount": r["amount"],
              "decision": r["decision"] or "OPEN", "approvedAmount": r["approved_amount"] or 0,
              "decidedBy": r["decided_by"]} for r in rows_]
    if new_case:
        log(f"Dispute {disputeId}: charge added - starting case {new_case['caseId']} "
            f"({new_case['merchantName']} {money(new_case['amount'])})")
    if pending:
        log(f"Dispute {disputeId}: {len(closed)}/{len(all_ids)} cases closed; still waiting on {', '.join(open_ids)}")
    else:
        log(f"Dispute {disputeId}: all {len(all_ids)} cases closed; dispute closing")
    return {"pending": pending, "openCases": open_ids, "caseCount": len(all_ids), "newCase": new_case,
            "totalDisputed": round(sum(r["amount"] for r in rows_), 2),
            "totalCredited": round(sum(r["approved_amount"] or 0 for r in closed), 2), "cases": cases}


# --------------------------------------------------------------------------- child
@worker_task(task_definition_name="open_case")
def open_case(caseId: str, disputeId: str, cardholderId: str, txnId: str, reasonCode: str,
              cardholderNote: str = "", workflowId: str = "") -> dict:
    opened = datetime.now(timezone.utc).replace(microsecond=0)
    deadline = (opened + timedelta(days=db.REG_Z_RESOLUTION_DAYS)).date().isoformat()
    with connect() as c:
        txn = transaction_view(c, txnId)
        existing = row(c, "SELECT opened_at, deadline FROM cases WHERE id=?", caseId)
        if existing:  # idempotent on retry
            log(f"Case {caseId} already open")
            return {"caseId": caseId, "openedAt": existing["opened_at"], "deadline": existing["deadline"],
                    "amount": txn["amount"]}
        c.execute("""INSERT INTO cases(id,dispute_id,cardholder_id,txn_id,workflow_id,reason_code,
                     cardholder_note,amount,opened_at,deadline) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                  (caseId, disputeId, cardholderId, txnId, workflowId, reasonCode, cardholderNote,
                   txn["amount"], opened.isoformat(), deadline))
    log(f"Opened case {caseId} for {txn['merchant_name']} {money(txn['amount'])}; resolve by {deadline}")
    return {"caseId": caseId, "openedAt": opened.isoformat(), "deadline": deadline, "amount": txn["amount"]}


@worker_task(task_definition_name="enrich_case")
def enrich_case(caseId: str, txnId: str, cardholderId: str, disputeId: str) -> dict:
    with connect() as c:
        t = transaction_view(c, txnId)
        prior = db.prior_disputes_90d(c, cardholderId, exclude_dispute=disputeId)
    outside = db.outside_window(t["statement_date"])
    out = {
        "merchantName": t["merchant_name"], "merchantCity": t["city"], "mcc": t["mcc"],
        "mccDescription": t["mcc_description"], "category": t["category"], "amount": t["amount"],
        "postedDate": t["posted_date"], "statementDate": t["statement_date"],
        "outsideWindow": "true" if outside else "false",
        "priorDisputes90d": prior, "merchantProfile": t["sim_behaviour"],
    }
    log(f"{t['merchant_name']} MCC {t['mcc']} ({t['category']}), {money(t['amount'])}, "
        f"statement {t['statement_date'] or 'current cycle'}, outsideWindow={out['outsideWindow']}, "
        f"prior disputes 90d={prior}")
    return out


@worker_task(task_definition_name="issue_provisional_credit")
def issue_provisional_credit(caseId: str, cardholderId: str, txnId: str, amount: float) -> dict:
    with connect() as c:
        c.execute("""INSERT OR IGNORE INTO ledger_entries(cardholder_id,txn_id,case_id,entry_type,amount,
                     created_at,memo) VALUES(?,?,?,?,?,?,?)""",
                  (cardholderId, txnId, caseId, "PROVISIONAL_CREDIT", amount, now_iso(),
                   "Provisional credit while dispute is investigated"))
        e = row(c, "SELECT id FROM ledger_entries WHERE case_id=? AND entry_type='PROVISIONAL_CREDIT'", caseId)
    log(f"Provisional credit {money(amount)} posted (ledger entry {e['id']})")
    return {"creditedAmount": amount, "ledgerEntryId": e["id"]}


@worker_task(task_definition_name="file_chargeback")
def file_chargeback(caseId: str, merchantName: str, amount: float, reasonCode: str,
                    merchantProfile: str = "") -> dict:
    """Calls the card network to open a chargeback. Network can be down -> retries."""
    attempt = get_task_context().get_retry_count() + 1
    with connect() as c:
        c.execute("UPDATE cases SET chargeback_attempts=? WHERE id=?", (attempt, caseId))
    # Outage scope: "all" fails every filing; a merchant name fails only that merchant's chargebacks
    # (the console uses VoltCity), so a live demo shows one case in trouble while the others carry on.
    scope = db.get_setting("outage_scope", "all")
    if db.get_setting("network_outage") == "on" and scope in ("all", merchantName):
        log(f"Attempt {attempt}: card network returned HTTP 503 Service Unavailable")
        raise RuntimeError("Card network unavailable (HTTP 503 Service Unavailable)")
    ref = f"CB-{uuid.uuid4().hex[:8].upper()}"
    log(f"Attempt {attempt}: chargeback {ref} filed with network for {merchantName} {money(amount)}")
    return {"chargebackRef": ref, "network": "VISA", "filedAt": now_iso(), "attempts": attempt}


@worker_task(task_definition_name="finalize_case")
def finalize_case(caseId: str, cardholderId: str, txnId: str, amount: float, decision: str,
                  approvedAmount: object = None, decidedBy: str = "", note: str = "",
                  provisionalCredit: object = None) -> dict:
    if db.get_setting("worker_bug") == "on":
        # Simulated deploy bug: deterministic, so retrying the task won't help. Fail hard (no retries),
        # the case workflow FAILS, ops fixes it and uses Retry, which resumes right here.
        log(f"Case {caseId}: ledger rejected the posting (schema mismatch after the 2.4.1 deploy)")
        raise NonRetryableException("LedgerPostingError: ledger API v2 rejected the posting (simulated bug)")
    decision = (decision or "REJECT").upper()
    amount = float(amount)
    if decision == "APPROVE":
        final = amount
    elif decision == "PARTIAL":
        final = max(0.0, min(amount, float(approvedAmount or 0)))
    else:
        final = 0.0
    credited = float(provisionalCredit or 0)
    with connect() as c:
        if credited and final < credited:
            c.execute("""INSERT OR IGNORE INTO ledger_entries(cardholder_id,txn_id,case_id,entry_type,amount,
                         created_at,memo) VALUES(?,?,?,?,?,?,?)""",
                      (cardholderId, txnId, caseId, "CREDIT_REVERSAL", -(credited - final), now_iso(),
                       f"Dispute {decision.lower()}: reverse {money(credited - final)}"))
        if final > credited:  # e.g. auto-deny path never credited
            c.execute("""INSERT OR IGNORE INTO ledger_entries(cardholder_id,txn_id,case_id,entry_type,amount,
                         created_at,memo) VALUES(?,?,?,?,?,?,?)""",
                      (cardholderId, txnId, caseId, "FINAL_CREDIT", final - credited, now_iso(), "Dispute credit"))
        c.execute("""UPDATE cases SET decision=?, approved_amount=?, decided_by=?, decision_note=?, closed_at=?
                     WHERE id=?""", (decision, final, decidedBy, note, now_iso(), caseId))
    outcome = {"APPROVE": f"Approved - {money(final)} credit is now permanent",
               "PARTIAL": f"Partially approved - {money(final)} of {money(amount)} credited",
               "REJECT": "Declined - charge stands"}.get(decision, decision)
    log(f"Case {caseId} closed: {outcome} (by {decidedBy})")
    return {"decision": decision, "approvedAmount": final,
            "reversedAmount": round(max(0.0, credited - final), 2), "outcome": outcome}


@worker_task(task_definition_name="notify_cardholder")
def notify_cardholder(cardholderId: str, kind: str, disputeId: str = "", caseId: str = "",
                      data: object = None) -> dict:
    """Writes a letter to the cardholder's in-app inbox (stands in for email/SMS/push)."""
    d = data or {}
    if kind == "RECEIVED":
        subject = f"We received your dispute {disputeId}"
        body = (f"We're reviewing {d.get('caseCount')} charge(s) totalling {money(float(d.get('totalDisputed', 0)))}. "
                "Each charge gets its own case and you'll hear from us as each one is resolved.")
    elif kind == "CHARGE_ADDED":
        subject = f"We added a charge to your dispute {disputeId}"
        body = (f"{d.get('merchantName', '')} {money(float(d.get('amount', 0)))} is now case {caseId}. "
                "It gets its own investigation, and your dispute stays open until every charge is resolved.")
    elif kind == "INFO_REQUEST":
        subject = f"Action needed on case {caseId}"
        body = d.get("question") or "Please tell us more about this charge."
    elif kind == "CASE_RESOLVED":
        subject = f"Case {caseId} resolved: {d.get('merchantName', '')}"
        body = d.get("outcome", "")
        auto_approved = d.get("decidedBy") == "RULES" and d.get("decision") == "APPROVE"
        if d.get("note") and not auto_approved:  # analyst notes / decline reasons, not internal auto notes
            body += f". Note from our team: {d['note']}"
    elif kind == "DISPUTE_SUMMARY":
        subject = f"Your dispute {disputeId} is complete"
        body = (f"All {d.get('caseCount')} charge(s) resolved. Total credited "
                f"{money(float(d.get('totalCredited', 0)))} of {money(float(d.get('totalDisputed', 0)))} disputed.")
    else:
        subject, body = kind, str(d)
    with connect() as c:
        db.add_message(c, cardholderId, disputeId, caseId, kind, subject, body)
    log(f"Sent {kind} to {cardholderId}: {subject}")
    return {"sent": True, "subject": subject}

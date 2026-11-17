"""Merchant / card-network simulator.

Plays the merchant answering chargebacks: a background loop auto-replies for merchants
whose profile says so; everything else is answered from the simulator page or left to
expire (the WAIT task's deadline = merchant forfeits, cardholder wins).
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone

from app import cases as live
from app.orkes import client
from bank import db
from bank.db import connect, rows

AUTO_REPLY_SECONDS = int(os.environ.get("MERCHANT_AUTO_REPLY_SECONDS", "20"))


def open_case_rows() -> list[dict]:
    with connect() as c:
        return rows(c, """
            SELECT cs.*, ch.name AS cardholder_name, m.name AS merchant_name, m.sim_behaviour,
                   m.contest_evidence, m.category, t.posted_date, t.description
            FROM cases cs
            JOIN cardholders ch ON ch.id = cs.cardholder_id
            JOIN transactions t ON t.id = cs.txn_id
            JOIN merchants m ON m.id = t.merchant_id
            WHERE cs.historical = 0 AND cs.workflow_id IS NOT NULL AND cs.closed_at IS NULL
            ORDER BY cs.opened_at""")


def respond(case: dict, decision: str, evidence: str = "", source: str = "simulator") -> None:
    state = live.live_state(case["workflow_id"])
    wait = state.get("merchantWait")
    if not wait:
        raise ValueError(f"Case {case['id']} is not waiting for a merchant response")
    payload = {"decision": decision, "respondedBy": source,
               "respondedAt": datetime.now(timezone.utc).isoformat()}
    if decision == "CONTEST":
        payload["evidence"] = evidence or case.get("contest_evidence") or "Merchant provided proof of transaction."
    client().complete_task_by_ref(case["workflow_id"], wait["taskRef"], payload)
    live.invalidate(case["workflow_id"])


def _auto_loop(stop: threading.Event) -> None:
    while not stop.wait(3):
        if db.get_setting("merchant_auto_reply", "on") != "on":
            continue
        try:
            for case in open_case_rows():
                profile = case.get("sim_behaviour") or ""
                if profile not in ("auto_accept", "contest", "flaky_contest"):
                    continue  # 'silent' expires, 'manual' waits for a click
                st = live.live_state(case["workflow_id"])
                wait = st.get("merchantWait")
                if not wait:
                    continue
                since = datetime.fromisoformat(wait["since"])
                if (datetime.now(timezone.utc) - since).total_seconds() < AUTO_REPLY_SECONDS:
                    continue
                decision = "ACCEPT" if profile == "auto_accept" else "CONTEST"
                respond(case, decision, source="auto")
                print(f"[merchant-sim] {case['id']} {case['merchant_name']}: auto {decision}", flush=True)
        except Exception as e:  # keep the loop alive during demos
            print(f"[merchant-sim] error: {e}", flush=True)
            time.sleep(2)


def start_background() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=_auto_loop, args=(stop,), daemon=True, name="merchant-sim").start()
    return stop

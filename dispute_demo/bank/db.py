"""SQLite 'core banking' system of record for the demo.

Conductor orchestrates; this database plays the bank's own systems: cardholders,
transactions, ledger (credits/reversals), case records and cardholder messages.
Shared by the web app and the worker processes.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "bank.db"

DISPUTE_WINDOW_DAYS = 60   # days after the statement date the charge first appeared on
REG_Z_RESOLUTION_DAYS = 90  # must resolve within two billing cycles / 90 days

SCHEMA = """
CREATE TABLE IF NOT EXISTS cardholders (
    id TEXT PRIMARY KEY, name TEXT, email TEXT, card_last4 TEXT, card_status TEXT,
    credit_limit REAL, persona TEXT
);
CREATE TABLE IF NOT EXISTS merchants (
    id TEXT PRIMARY KEY, name TEXT, mcc TEXT, mcc_description TEXT, category TEXT,
    city TEXT, sim_behaviour TEXT, contest_evidence TEXT
);
CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY, cardholder_id TEXT, merchant_id TEXT, amount REAL,
    posted_date TEXT, statement_date TEXT, description TEXT
);
CREATE TABLE IF NOT EXISTS disputes (
    id TEXT PRIMARY KEY, cardholder_id TEXT, workflow_id TEXT, created_at TEXT,
    item_count INTEGER
);
CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY, dispute_id TEXT, cardholder_id TEXT, txn_id TEXT,
    workflow_id TEXT, reason_code TEXT, cardholder_note TEXT, amount REAL,
    opened_at TEXT, deadline TEXT, closed_at TEXT, decision TEXT,
    approved_amount REAL, decided_by TEXT, decision_note TEXT,
    chargeback_attempts INTEGER DEFAULT 0, historical INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ledger_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT, cardholder_id TEXT, txn_id TEXT, case_id TEXT,
    entry_type TEXT, amount REAL, created_at TEXT, memo TEXT,
    UNIQUE(case_id, entry_type)
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, cardholder_id TEXT, dispute_id TEXT,
    case_id TEXT, kind TEXT, subject TEXT, body TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""

REASONS = {
    "NOT_RECEIVED": "Goods or services not received",
    "CANCELLED": "Cancelled but still charged",
    "UNAUTHORIZED": "I didn't make this charge",
    "DUPLICATE": "Charged more than once",
    "NOT_AS_DESCRIBED": "Work not done / not as described",
    "WRONG_AMOUNT": "Charged the wrong amount",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_schema(conn) -> None:
    conn.executescript(SCHEMA)


def rows(conn, sql: str, *args) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def row(conn, sql: str, *args) -> dict | None:
    r = conn.execute(sql, args).fetchone()
    return dict(r) if r else None


# -- settings (shared flags between web app and worker processes) ---------
def get_setting(key: str, default: str = "") -> str:
    with connect() as c:
        r = row(c, "SELECT value FROM settings WHERE key=?", key)
    return r["value"] if r else default


def set_setting(key: str, value: str) -> None:
    with connect() as c:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


# -- domain helpers ------------------------------------------------------
def transaction_view(conn, txn_id: str) -> dict | None:
    return row(conn, """
        SELECT t.*, m.name AS merchant_name, m.mcc, m.mcc_description, m.category,
               m.city, m.sim_behaviour, m.contest_evidence
        FROM transactions t JOIN merchants m ON m.id = t.merchant_id WHERE t.id = ?""", txn_id)


def outside_window(statement_date: str | None, today: date | None = None) -> bool:
    if not statement_date:  # still in the current cycle
        return False
    today = today or date.today()
    return today > date.fromisoformat(statement_date) + timedelta(days=DISPUTE_WINDOW_DAYS)


def prior_disputes_90d(conn, cardholder_id: str, exclude_dispute: str | None = None) -> int:
    since = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    r = row(conn, """SELECT COUNT(*) AS n FROM cases WHERE cardholder_id=? AND opened_at>=?
                     AND (dispute_id != ? OR ? IS NULL)""",
            cardholder_id, since, exclude_dispute, exclude_dispute)
    return r["n"]


def add_message(conn, cardholder_id, dispute_id, case_id, kind, subject, body) -> None:
    conn.execute("""INSERT INTO messages(cardholder_id,dispute_id,case_id,kind,subject,body,created_at)
                    VALUES(?,?,?,?,?,?,?)""",
                 (cardholder_id, dispute_id, case_id, kind, subject, body, now_iso()))


def to_json(v) -> str:
    return json.dumps(v, default=str)

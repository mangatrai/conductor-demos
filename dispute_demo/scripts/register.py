"""Register task definitions, the analyst form and both workflows in Orkes.

    python scripts/register.py

If DISPUTE_RULES_URL is set (in the workspace .env or the environment), triage uses a
BUSINESS_RULE task reading that CSV. Otherwise it falls back to an INLINE task with the
same rules and the same output shape ({result: {route, reason}}).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.orkes import OrkesError, client  # noqa: E402

LABOR = ["CONTRACTOR", "HOME_SERVICES", "PERSONAL_SERVICES", "PROFESSIONAL_SERVICES", "REPAIR"]

RULE_INPUTS = {
    "outsideWindow": "${enrich_case.output.outsideWindow}",
    "amount": "${enrich_case.output.amount}",
    "category": "${enrich_case.output.category}",
    "priorDisputes90d": "${enrich_case.output.priorDisputes90d}",
}


def triage_task() -> dict:
    url = os.environ.get("DISPUTE_RULES_URL", "").strip()
    if url:
        return {
            "name": "triage_rules",
            "taskReferenceName": "triage_rules",
            "type": "BUSINESS_RULE",
            "description": "Dispute triage decision table (rules/dispute_rules.csv). First matching row wins.",
            "inputParameters": {
                "ruleFileLocation": url,
                "executionStrategy": "FIRE_FIRST",
                "cacheTimeoutMinutes": 1,
                "inputColumns": RULE_INPUTS,
                "outputColumns": ["route", "reason"],
            },
        }
    labor = json.dumps(LABOR)
    expr = (
        "(function () { var labor = " + labor + "; "
        "if ($.outsideWindow == 'true') { return { route: 'AUTO_DENY', reason: 'Outside the 60-day dispute window' }; } "
        "if (Number($.amount) > 100) { return { route: 'HUMAN_REVIEW', reason: 'Amount over $100' }; } "
        "if (labor.indexOf($.category) >= 0) { return { route: 'HUMAN_REVIEW', reason: 'Human-labor service category' }; } "
        "if (Number($.priorDisputes90d) > 3) { return { route: 'HUMAN_REVIEW', reason: 'Repeat disputer (more than 3 disputes in 90 days)' }; } "
        "return { route: 'AUTO_APPROVE', reason: 'Low-risk dispute' }; })()"
    )
    return {
        "name": "triage_rules",
        "taskReferenceName": "triage_rules",
        "type": "INLINE",
        "description": "Dispute triage rules (fallback while the BUSINESS_RULE CSV URL is not configured).",
        "inputParameters": {"evaluatorType": "graaljs", **RULE_INPUTS, "expression": expr},
    }


def load(rel: str):
    return json.loads((ROOT / rel).read_text())


def main() -> None:
    o = client()

    task_defs = load("workflows/task_defs.json")
    try:
        o.register_task_defs(task_defs)
        print(f"Created {len(task_defs)} task definitions")
    except OrkesError:
        o.update_task_defs(task_defs)
        print(f"Updated {len(task_defs)} task definitions")

    o.save_user_form(load("forms/dispute_review_form.json"))
    print("Saved user form dispute_review_form v1")

    case_wf = load("workflows/dispute_case.json")
    triage = triage_task()
    case_wf["tasks"] = [triage if t == "__TRIAGE_TASK__" else t for t in case_wf["tasks"]]
    intake_wf = load("workflows/dispute_intake.json")
    o.upsert_workflow_defs([case_wf, intake_wf])
    print(f"Registered workflows dispute_case (triage: {triage['type']}) and dispute_intake")
    print(f"Orkes UI: {o.ui_base}/workflowDef/dispute_intake")


if __name__ == "__main__":
    main()

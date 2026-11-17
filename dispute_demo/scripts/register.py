"""Register the triage decision rule, task definitions, user forms and both workflows in Orkes.

    python scripts/register.py

Triage is a BUSINESS_RULE task that references a decision rule saved in Orkes by name
(Orkes 5.6+: Definitions > Decision Rules). rules/dispute_rules.csv is that rule's starting
content: every run of this script saves it, so a demo always starts from the repo's rules.
Edit the rule live in the Orkes UI; the next case uses it, with no deploy and no cache delay.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.orkes import OrkesError, client  # noqa: E402

RULE_NAME = "dispute_triage_rules"
RULE_INPUTS = {
    "outsideWindow": "${enrich_case.output.outsideWindow}",
    "amount": "${enrich_case.output.amount}",
    "category": "${enrich_case.output.category}",
    "priorDisputes90d": "${enrich_case.output.priorDisputes90d}",
}


def save_rule(o) -> None:
    csv = (ROOT / "rules" / "dispute_rules.csv").read_text()
    try:
        o.call("POST", "/business-rules", json={"name": RULE_NAME, "csvData": csv})
    except OrkesError as e:
        if e.status == 403:
            sys.exit(f"Orkes refused to save decision rule '{RULE_NAME}' (403). Give the application behind "
                     "CONDUCTOR_AUTH_KEY the 'Business Rule Manager' (or Metadata Manager) role in "
                     "Access Control > Applications, then run this again.")
        raise
    print(f"Saved decision rule {RULE_NAME} from rules/dispute_rules.csv")


def triage_task() -> dict:
    return {
        "name": "triage_rules",
        "taskReferenceName": "triage_rules",
        "type": "BUSINESS_RULE",
        "description": f"Dispute triage: decision rule '{RULE_NAME}' (Definitions > Decision Rules). First matching row wins.",
        "inputParameters": {
            "ruleName": RULE_NAME,
            "executionStrategy": "FIRE_FIRST",
            "inputColumns": RULE_INPUTS,
            "outputColumns": ["route", "reason"],
        },
    }


def load(rel: str):
    return json.loads((ROOT / rel).read_text())


def main() -> None:
    o = client()
    save_rule(o)

    task_defs = load("workflows/task_defs.json")
    try:
        o.register_task_defs(task_defs)
        print(f"Created {len(task_defs)} task definitions")
    except OrkesError:
        o.update_task_defs(task_defs)
        print(f"Updated {len(task_defs)} task definitions")

    for form_file in sorted((ROOT / "forms").glob("*.json")):
        form = json.loads(form_file.read_text())
        o.save_user_form(form)
        print(f"Saved user form {form['name']} v{form['version']}")

    case_wf = load("workflows/dispute_case.json")
    triage = triage_task()
    case_wf["tasks"] = [triage if t == "__TRIAGE_TASK__" else t for t in case_wf["tasks"]]
    intake_wf = load("workflows/dispute_intake.json")
    o.upsert_workflow_defs([case_wf, intake_wf])
    print(f"Registered workflows dispute_case (triage: decision rule {RULE_NAME}) and dispute_intake")
    print(f"Orkes UI: {o.ui_base}/workflowDef/dispute_intake")


if __name__ == "__main__":
    main()

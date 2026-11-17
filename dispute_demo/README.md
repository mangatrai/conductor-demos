# Credit card dispute demo (Orkes Conductor)

One cardholder dispute → **one case per charge**, each with its own lifecycle → the **parent closes last**.

```
dispute_intake (parent, correlationId = dispute ID)
 ├─ validate_cardholder → card_status (SWITCH / TERMINATE)
 ├─ prepare_cases → notify_cardholder (received)
 ├─ case_per_charge  FORK_JOIN_DYNAMIC → dispute_case × N   (optional: one failed case never cancels siblings)
 ├─ wait_for_all_cases  JOIN
 └─ summarize_dispute (INLINE) → notify_cardholder (summary letter)

dispute_case (one per charge)
 open_case → enrich_case → triage_rules (BUSINESS_RULE decision table, or INLINE fallback)
 └─ route_case SWITCH
     AUTO_DENY → set decision REJECT
     default   → issue_provisional_credit → file_chargeback (6 retries, exponential backoff)
                → await_merchant_response (WAIT, 3 min demo deadline; completed early by merchant reply)
                → merchant_outcome (INLINE) → needs_review SWITCH
                     YES → review_loop DO_WHILE [ analyst_review HUMAN → REQUEST_INFO? notify + await_cardholder_info WAIT ]
                     NO  → set decision APPROVE
 finalize_case (ledger: keep / partially reverse / reverse credit) → notify_cardholder
```

Triage rules (`rules/dispute_rules.csv`, first match wins):

| outsideWindow | amount | category | priorDisputes90d | route |
|---|---|---|---|---|
| true | | | | AUTO_DENY |
| | >100 | | | HUMAN_REVIEW |
| | | contractor / home / personal / professional services / repair | | HUMAN_REVIEW |
| | | | >3 | HUMAN_REVIEW |
| | | | | AUTO_APPROVE |

## Run

```bash
cd /Users/mrai/sandbox/castles/conductor/dispute_demo
uv pip install --python /Users/mrai/.uv/venvs/conductor -r requirements.txt   # once
/Users/mrai/.uv/venvs/conductor/bin/python scripts/register.py                # task defs, form, workflows
/Users/mrai/.uv/venvs/conductor/bin/python run.py                             # workers + web app
```

- Cardholder portal: http://localhost:8000/
- Analyst console: http://localhost:8000/admin
- Card network / merchant simulator: http://localhost:8000/merchant

Credentials come from the workspace `.env` (`CONDUCTOR_SERVER_URL`, `CONDUCTOR_AUTH_KEY`,
`CONDUCTOR_AUTH_SECRET`). Triage is a BUSINESS_RULE task that reads the decision table straight
from this repo:

```
DISPUTE_RULES_URL=https://raw.githubusercontent.com/mangatrai/conductor-demos/main/dispute_demo/rules/dispute_rules.csv
```

Add that line to `.env` and re-run `register.py`. Rules are cached for 1 minute, so an edit to the CSV
pushed to `main` takes effect on the next dispute about a minute later (GitHub's raw CDN can add a few
minutes). Without the URL, triage falls back to an INLINE task with the same rules and output shape.

Reset between demos: `python scripts/reset_demo.py` (add `--purge` to delete old executions).
Full end-to-end check (app must be running): `python scripts/smoke_test.py`.

## Synthetic data

`bank/seed.py` → `bank/bank.db` (SQLite: the bank's systems of record). There are 4 personas, each with about 45 transactions over the last 3 months. Merchants are fictional; the MCC codes are real.

| Persona | Story |
|---|---|
| Priya Shah (CH-1001) | Scripted scenario: StreamMax $15.99, VoltCity $649 (flaky merchant, contests), Ace Rapid Plumbing $85 (labor), SkyBridge $389 (outside window) |
| Marcus Johnson (CH-1002) | Homeowner: contractors, cleaning, landscaping, a $1,250 sofa |
| Elena Rossi (CH-1003) | Traveler: duplicate hotel charge, rental car fuel surcharge |
| Jordan Lee (CH-1004) | Repeat disputer: 4 disputes in the last 90 days, so every new case goes to review |

Merchant simulator profiles:
- `auto_accept`: accepts after 20s.
- `contest` / `flaky_contest`: contests after 20s. `flaky_contest` also times out on the first 2 chargeback attempts.
- `silent`: never answers, so the 3-minute deadline passes and the cardholder wins.
- `manual`: waits for a click.

## Demo script (~15 min)

1. **Intake.** In the portal as Priya, select StreamMax, VoltCity and Ace Rapid Plumbing, choose a reason for each, and submit.
   Open the parent in Orkes: three `dispute_case` sub-workflows run side by side under one dispute.
2. **One finishes first.** StreamMax: rules auto-approve it, provisional credit is posted, the merchant
   auto-accepts and the case resolves. The portal timeline updates live.
3. **Durability.** VoltCity's acquirer times out twice; show the retries with backoff in the Orkes
   timeline and Logs tab. For a bigger moment, turn **Network outage** on in the simulator before
   submitting, then off: every case recovers on its own. You can also stop the workers (Ctrl+C) mid-flow and
   restart `run.py`; nothing is lost.
4. **Human in the loop.** VoltCity (over $100) and Ace (human labor) arrive in the analyst queue with the reason they're there
   and the merchant's evidence. On Ace, choose **Request info**: the case pauses, and Priya sees the question
   in her portal and answers it. The case returns to the queue with her answer, and you **partially approve** $40.
5. **Parent closes last.** After the last case resolves, the parent completes and Priya gets one summary letter.
6. **Rules are config.** Open `triage_rules` in the workflow editor (or the CSV): change `>100` to `>500`,
   wait 1 minute (rule cache), and dispute a $300 charge as Marcus. It now auto-approves.
7. **Customer questions:**
   - *User task management:* Show the form **Definitions → User Forms → dispute_review_form** (drag-and-drop
     builder, JSON schema validation), the Orkes Human Tasks inbox, assignment to `dispute-analysts` with a 4h
     SLA escalating to `dispute-supervisors`, and the same task worked from the bank's own console via API.
   - *Search:* Use the console's Search tab or Orkes Executions search with a dispute ID (correlation ID), a case ID,
     `CH-1001`, a merchant name or `HUMAN_REVIEW`. That's free text over workflow input and output. Be honest that there
     are no typed custom search attributes; the pattern is a correlation ID plus indexed input and output.
   - *Observability:* Execution diagram, timeline, per-task input/output/logs, retry history, workflow
     variables, Task Queues page (worker poll status), and restart/retry from a failed task.

## Notes
- Orkes is the source of truth for where a case is: the UI reads the execution directly, so there is no status-sync code.
- The Python SDK (2.0.0) has no human-task client, so `app/orkes.py` calls `/api/human/tasks/*` REST directly.
- When retries run out (an outage longer than about 2 minutes), the case fails and shows **Needs attention**. Its sibling cases carry on (the fork is `optional`).

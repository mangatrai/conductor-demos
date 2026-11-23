"""v3 terminal chat: every message is one run of convo_v3_chat_turn (with portfolio lookups).

    python -m v3.chat            # new session
    python -m v3.chat --resume   # continue the session saved in .run/v3_session.json

Commands: /new  /quit
"""
import argparse
import json
import os
import sys
import uuid

from common import RUN_DIR
from common.conductor import Conductor, ConductorError

WORKFLOW = "convo_v3_chat_turn"
SESSION_FILE = os.path.join(RUN_DIR, "v3_session.json")


def new_state():
    return {"sessionId": "v3-" + uuid.uuid4().hex[:8], "executionId": ""}


def save(state):
    os.makedirs(RUN_DIR, exist_ok=True)
    with open(SESSION_FILE, "w") as f:
        json.dump(state, f)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v3 chat (portfolio lookups)")
    ap.add_argument("--resume", action="store_true", help="continue the last saved session")
    a = ap.parse_args(argv)
    state = new_state()
    if a.resume and os.path.exists(SESSION_FILE):
        state = json.load(open(SESSION_FILE))
    c = Conductor()
    print("v3 chat - session %s. Try: What's in Jane Doe's portfolio?  (/new, /quit)" % state["sessionId"])
    for line in sys.stdin:
        msg = line.strip()
        if not msg:
            continue
        if msg == "/quit":
            break
        if msg == "/new":
            state = new_state()
            print("(new session %s)" % state["sessionId"])
            continue
        try:
            run = c.run_sync(WORKFLOW, {"sessionId": state["sessionId"], "prevExecutionId": state["executionId"],
                                        "message": msg}, correlation_id=state["sessionId"], wait_seconds=150)
        except ConductorError as e:
            print("(conductor error: %s)" % e)
            continue
        out = run.get("output") or {}
        if run.get("status") != "COMPLETED":
            print("(turn %s: %s)" % (run.get("status"), run.get("reasonForIncompletion") or "see %s" % c.ui_url(run.get("workflowId"))))
            continue
        lk = out.get("lookup")
        if lk:
            what = "unavailable" if lk.get("error") else ("total %s" % lk.get("totalValue") if lk.get("found") else "not found")
            print("  [looked up %s: %s - %s]" % (lk.get("clientName"), what, c.ui_url(lk.get("subWorkflowId"))))
        print("bot> %s" % out.get("reply", ""))
        state["executionId"] = out.get("executionId") or run.get("workflowId")
        save(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())

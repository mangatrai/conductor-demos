"""v1 terminal chat: every message is one run of the convo_v1_chat_turn workflow.

    python -m v1.chat                       # new session
    python -m v1.chat --resume              # continue the session saved in .run/v1_session.json
    python -m v1.chat --session S --resume EXEC_ID
    python -m v1.chat --model qwen2.5:3b    # model/provider swap through input only

Commands: /new  /history  /links  /quit
"""
import argparse
import json
import os
import sys
import uuid

from common import RUN_DIR
from common.conductor import Conductor, ConductorError

WORKFLOW = "convo_v1_chat_turn"
SESSION_FILE = os.path.join(RUN_DIR, "v1_session.json")


def new_session_id():
    return "v1-" + uuid.uuid4().hex[:8]


def next_pointer(run, prev):
    """Only a COMPLETED run advances the memory pointer."""
    if run.get("status") == "COMPLETED":
        return (run.get("output") or {}).get("executionId") or run.get("workflowId") or prev
    return prev


def format_turn(run):
    status = run.get("status")
    if status == "COMPLETED":
        return "bot> %s" % (run.get("output") or {}).get("reply", "")
    if status in ("RUNNING", "PAUSED", "SCHEDULED"):
        return "(still running, open the execution link to watch it)"
    return "(turn %s: %s)" % (status, run.get("reasonForIncompletion") or "no reason given")


def save_pointer(session_id, execution_id):
    os.makedirs(RUN_DIR, exist_ok=True)
    with open(SESSION_FILE, "w") as f:
        json.dump({"sessionId": session_id, "executionId": execution_id}, f)


def load_pointer():
    try:
        with open(SESSION_FILE) as f:
            d = json.load(f)
        return d.get("sessionId"), d.get("executionId", "")
    except (OSError, ValueError):
        return None, ""


def main(argv=None):
    ap = argparse.ArgumentParser(description="v1 chat: one workflow execution per message")
    ap.add_argument("--session", help="session id (correlationId)")
    ap.add_argument("--resume", nargs="?", const="__saved__", default=None,
                    help="resume: no value = last saved session; or a previous execution id")
    ap.add_argument("--provider", help="override llmProvider input")
    ap.add_argument("--model", help="override model input")
    args = ap.parse_args(argv)

    session, prev = args.session, ""
    if args.resume == "__saved__":
        saved_session, saved_prev = load_pointer()
        if saved_session:
            session, prev = session or saved_session, saved_prev
        else:
            print("(no saved session to resume, starting a new one)")
    elif args.resume:
        prev = args.resume
    session = session or new_session_id()

    client = Conductor()
    print("v1 chat, session %s. Type /quit to leave, /new, /history, /links." % session)
    print("session: %s" % client.ui_url(correlation_id=session))
    if prev:
        print("resuming from execution %s" % prev)
    last_output, first_turn = {}, True

    while True:
        try:
            sys.stdout.write("you> ")
            sys.stdout.flush()
            line = sys.stdin.readline()
        except KeyboardInterrupt:
            print()
            break
        if not line:
            break
        msg = line.strip()
        if not msg:
            continue
        if msg == "/quit":
            break
        if msg == "/new":
            session, prev, last_output, first_turn = new_session_id(), "", {}, True
            print("new session %s\nsession: %s" % (session, client.ui_url(correlation_id=session)))
            continue
        if msg == "/history":
            for m in last_output.get("history", []):
                print("  %-9s %s" % (m.get("role"), m.get("message")))
            continue
        if msg == "/links":
            print("session: %s" % client.ui_url(correlation_id=session))
            if prev:
                print("execution: %s" % client.ui_url(workflow_id=prev))
            continue

        inp = {"sessionId": session, "prevExecutionId": prev, "message": msg}
        if args.provider:
            inp["llmProvider"] = args.provider
        if args.model:
            inp["model"] = args.model
        try:
            run = client.run_sync(WORKFLOW, inp, correlation_id=session, wait_seconds=120)
        except ConductorError as e:
            print("(conductor error: %s)" % e)
            continue
        out = run.get("output") or {}
        if run.get("status") == "COMPLETED" and first_turn and out.get("restored"):
            print("(memory restored)")
        print(format_turn(run))
        print("  ↳ execution: %s" % client.ui_url(workflow_id=run.get("workflowId")))
        if run.get("status") == "COMPLETED":
            first_turn, last_output = False, out
            prev = next_pointer(run, prev)
            save_pointer(session, prev)
    print("bye. session: %s" % client.ui_url(correlation_id=session))
    return 0


if __name__ == "__main__":
    sys.exit(main())

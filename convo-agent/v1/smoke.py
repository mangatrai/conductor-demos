"""v1 smoke: two real turns chained by executionId; turn 2 must remember turn 1. Exit 0/1."""
import sys
import uuid

from common.conductor import Conductor, ConductorError

WORKFLOW = "convo_v1_chat_turn"


def main():
    c = Conductor()
    session = "v1-smoke-" + uuid.uuid4().hex[:8]
    print("session: %s" % c.ui_url(correlation_id=session))
    prev, run = "", None
    try:
        for msg in ("I am 55 and plan to retire at 62.", "How many years until I retire?"):
            run = c.run_sync(WORKFLOW, {"sessionId": session, "prevExecutionId": prev, "message": msg},
                             correlation_id=session, wait_seconds=150)
            print("execution: %s  (%s)" % (c.ui_url(workflow_id=run.get("workflowId")), run.get("status")))
            if run.get("status") != "COMPLETED":
                print("FAIL: turn %r ended %s: %s" % (msg, run.get("status"), run.get("reasonForIncompletion")))
                return 1
            prev = run["output"]["executionId"]
    except ConductorError as e:
        print("FAIL: %s" % e)
        return 1
    out = run["output"]
    reply = str(out.get("reply", ""))
    print("reply: %s" % reply)
    ok = out.get("restored") is True and len(out.get("history") or []) == 4 \
        and ("7" in reply or "seven" in reply.lower())
    print("PASS" if ok else "FAIL: restored=%r history=%d" % (out.get("restored"), len(out.get("history") or [])))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

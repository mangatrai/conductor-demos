"""v3 smoke: one real portfolio turn and one plain turn against the running stack.

    python -m v3.smoke        (needs Conductor, Ollama and the v3 mock API on 8731: ./convo.sh start v3)
"""
import sys
import uuid

from common.conductor import Conductor

WORKFLOW = "convo_v3_chat_turn"


def turn(client, message):
    sid = "smoke-v3-" + uuid.uuid4().hex[:8]
    run = client.run_sync(WORKFLOW, {"sessionId": sid, "prevExecutionId": "", "message": message},
                          correlation_id=sid, wait_seconds=150)
    out = run.get("output") or {}
    print("[%s] %s -> %s" % (run.get("status"), message, (out.get("reply") or "")[:160].replace("\n", " ")))
    if run.get("status") != "COMPLETED":
        raise SystemExit("FAIL: %s is %s: %s" % (WORKFLOW, run.get("status"), run.get("reasonForIncompletion")))
    return out


def main():
    c = Conductor()
    out = turn(c, "What's in Jane Doe's portfolio?")
    lk = out.get("lookup")
    print("  lookup:", lk)
    if not isinstance(lk, dict) or lk.get("found") is not True:
        raise SystemExit("FAIL: expected lookup.found=true (is the mock API running on 8731?)")
    reply = out.get("reply") or ""
    if not any(s in reply for s in ("1,250,000", "1.25", "1250000")):
        raise SystemExit("FAIL: reply lacks Jane Doe's total value 1,250,000")
    print("  sub workflow:", c.ui_url(lk.get("subWorkflowId")))

    out = turn(c, "Hi, what can you do?")
    if out.get("lookup") is not None:
        raise SystemExit("FAIL: plain question ran a lookup: %r" % out.get("lookup"))
    print("OK: v3 smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

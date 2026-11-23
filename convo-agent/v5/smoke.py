"""python -m v5.smoke: probe, then two turns in one session; the second must remember (7 years)."""
import json
import re
import sys
import time
import uuid

from common.conductor import Conductor
from v5 import probe
from v5.turn import run_turn


def main():
    c = Conductor()
    report = probe.probe(c)
    print("probe: " + json.dumps({k: report[k] for k in ("aiEnabled", "agentTask", "sdkSessionMemory")}))
    s = "smoke-v5-" + uuid.uuid4().hex[:8]
    r1 = run_turn(s, "My client is 55, retiring at 62")
    r2 = run_turn(s, "How many years left?", r1["executionId"])
    print("reply: %s" % r2["reply"])
    print("memorySource: %s  agentMode: %s  restored: %s" % (r2.get("memorySource"), r2.get("agentMode"), r2.get("restored")))
    print("executions: %s %s" % (r1["uiUrl"], r2["uiUrl"]))
    problems = []
    if not re.search(r"\b7\b|\bseven\b", r2.get("reply") or "", re.I):
        problems.append("second reply does not say 7 years")
    if r2.get("restored") is not True:
        problems.append("second turn did not restore history")
    want, found = {r1["executionId"], r2["executionId"]}, set()
    for _ in range(30):  # search index may lag
        found = {x.get("workflowId") for x in c.search_by_correlation(s)}
        if want <= found:
            break
        time.sleep(1)
    if not want <= found:
        problems.append("correlation search did not find both executions")
    print("smoke v5: " + ("FAIL: " + "; ".join(problems) if problems else "ok"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

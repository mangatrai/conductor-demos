"""v2 smoke: two real turns through the front door, then resume the session.

    python -m v2.smoke [--base http://localhost:8720]
"""
import argparse
import sys
import uuid

import requests


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8720")
    base = ap.parse_args(argv).base.rstrip("/")

    def fail(why):
        print("FAIL: " + why)
        return 1

    try:
        if requests.get(base + "/healthz", timeout=5).json().get("ok") is not True:
            return fail("/healthz not ok")
    except Exception as e:
        return fail("front door not reachable at %s: %s" % (base, e))

    sid = "v2-smoke-" + uuid.uuid4().hex[:8]
    prev = ""
    r = None
    for msg in ("My client is 55 and wants to retire at 62.", "How many years does he have?"):
        try:
            resp = requests.post(base + "/api/chat", timeout=150,
                                 json={"sessionId": sid, "prevExecutionId": prev, "message": msg})
            r = resp.json()
        except Exception as e:
            return fail("turn %r failed: %s" % (msg, e))
        if resp.status_code != 200:
            return fail("turn %r -> HTTP %s: %s" % (msg, resp.status_code, r.get("error")))
        prev = r["executionId"]
        print("> %s\n< %s\n  execution: %s" % (msg, r.get("reply", "").strip(), r.get("uiUrl")))

    reply = (r.get("reply") or "").lower()
    if "7" not in reply and "seven" not in reply:
        return fail("second reply does not mention 7 years: %r" % reply)

    s = requests.get(base + "/api/session", params={"sessionId": sid, "executionId": prev}, timeout=60).json()
    if s.get("found") is not True or len(s.get("history", [])) != 4:
        return fail("session resume did not return 4 history items: %s" % s)
    print("session: %s\nPASS" % r.get("sessionUrl"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

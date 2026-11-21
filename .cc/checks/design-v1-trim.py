#!/usr/bin/env python3
"""v1: 25 chained turns -> final history has 20 messages, starts with user, roles alternate."""
import json, os, subprocess, sys, time, urllib.request, uuid

ROOT = os.path.join(os.getcwd(), "convo-agent")
API = os.environ.get("CONDUCTOR_SERVER_URL", "http://localhost:8080/api").rstrip("/")
DEADLINE = time.time() + 1500


def fail(msg):
    print("FAIL: " + msg)
    sys.exit(1)


def http(method, path, body=None, timeout=20):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode()
    return raw


def sh(*args, t=600):
    return subprocess.run(["./convo.sh", *args], cwd=ROOT, capture_output=True, text=True, timeout=t)


def main():
    if not os.path.isfile(os.path.join(ROOT, "convo.sh")):
        fail("convo-agent/convo.sh does not exist")
    try:
        r = sh("start", "v1")
    except subprocess.TimeoutExpired:
        fail("./convo.sh start v1 timed out")
    if r.returncode != 0:
        fail("./convo.sh start v1 exited %d" % r.returncode)
    try:
        session = "trim-" + uuid.uuid4().hex[:8]
        prev, hist = "", None
        for i in range(25):
            if time.time() > DEADLINE:
                fail("deadline passed at turn %d" % (i + 1))
            body = {"name": "convo_v1_chat_turn", "version": 1, "correlationId": session,
                    "input": {"sessionId": session, "prevExecutionId": prev,
                              "message": "Say OK (turn %d)." % (i + 1),
                              "systemPrompt": "Reply with the single word OK."}}
            try:
                wid = http("POST", "/workflow", body).strip().strip('"')
            except Exception as e:
                fail("start turn %d: %s" % (i + 1, e))
            wf = None
            while time.time() < DEADLINE:
                wf = json.loads(http("GET", "/workflow/%s?includeTasks=false" % wid))
                if wf["status"] != "RUNNING":
                    break
                time.sleep(0.5)
            if not wf or wf["status"] != "COMPLETED":
                fail("turn %d not COMPLETED (%s)" % (i + 1, wf and wf["status"]))
            out = wf["output"]
            prev, hist = out["executionId"], out["history"]
        if len(hist) != 20:
            fail("history has %d messages, expected 20" % len(hist))
        if hist[0]["role"] != "user":
            fail("first message role is %s" % hist[0]["role"])
        for i, m in enumerate(hist):
            if m["role"] != ("user" if i % 2 == 0 else "assistant"):
                fail("roles do not alternate at index %d" % i)
        print("OK")
    finally:
        try:
            sh("stop", "v1", t=120)
        except Exception:
            pass


main()

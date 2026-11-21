import json, os, subprocess, sys, time, urllib.request, uuid

ROOT = os.path.join(os.getcwd(), "convo-agent")
API = os.environ.get("CONDUCTOR_SERVER_URL", "http://localhost:8080/api").rstrip("/")


def fail(msg):
    print("FAIL: " + msg)
    sys.exit(1)


def http(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode()


def run_turn(session, prev, message):
    wid = http("POST", "/workflow", {
        "name": "convo_v1_chat_turn", "version": 1, "correlationId": session,
        "input": {"sessionId": session, "prevExecutionId": prev, "message": message}}).strip().strip('"')
    deadline = time.time() + 150
    while time.time() < deadline:
        wf = json.loads(http("GET", "/workflow/" + wid + "?includeTasks=false"))
        if wf["status"] == "COMPLETED":
            return wid, wf["output"]
        if wf["status"] not in ("RUNNING", "PAUSED"):
            fail("turn ended %s: %s" % (wf["status"], wf.get("reasonForIncompletion")))
        time.sleep(1)
    fail("turn did not complete within 150s")


def main():
    if not os.path.isfile(os.path.join(ROOT, "convo.sh")):
        fail("convo-agent/convo.sh does not exist")
    try:
        try:
            r = subprocess.run(["./convo.sh", "start", "v1"], cwd=ROOT, capture_output=True, text=True, timeout=500)
        except subprocess.TimeoutExpired:
            fail("./convo.sh start v1 timed out")
        if r.returncode != 0:
            fail("./convo.sh start v1 exited %d" % r.returncode)
        session = "chk-" + uuid.uuid4().hex[:8]
        w1, o1 = run_turn(session, "", "I am 55 and plan to retire at 62")
        w2, o2 = run_turn(session, w1, "How many years until I retire?")
        reply = str(o2.get("reply", "")).lower()
        if "7" not in reply and "seven" not in reply:
            fail("reply does not mention 7/seven: %r" % reply[:120])
        if o2.get("restored") is not True:
            fail("restored is %r, expected true" % o2.get("restored"))
        if len(o2.get("history", [])) != 4:
            fail("history has %d messages, expected 4" % len(o2.get("history", [])))
    except SystemExit:
        raise
    except Exception as e:
        fail("%s: %s" % (type(e).__name__, e))
    finally:
        try:
            subprocess.run(["./convo.sh", "stop"], cwd=ROOT, capture_output=True, timeout=120)
        except Exception:
            pass
    print("OK")


main()

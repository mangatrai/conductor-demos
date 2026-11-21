import json, os, subprocess, sys, time, urllib.request, uuid

ROOT = os.path.join(os.getcwd(), "convo-agent")
API = os.environ.get("CONDUCTOR_SERVER_URL", "http://localhost:8080/api").rstrip("/")
MODEL = "qwen2.5:3b"
NAME = "convo_v1_chat_turn"


def fail(msg):
    print("FAIL: " + msg)
    sys.exit(1)


def http(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode()


def definition():
    return json.loads(http("GET", "/metadata/workflow/%s?version=1" % NAME))


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
        before = definition()
        session = "chk-" + uuid.uuid4().hex[:8]
        wid = http("POST", "/workflow", {
            "name": NAME, "version": 1, "correlationId": session,
            "input": {"sessionId": session, "prevExecutionId": "",
                      "message": "Say hello in one short sentence.", "model": MODEL}}).strip().strip('"')
        deadline = time.time() + 150
        wf = None
        while time.time() < deadline:
            wf = json.loads(http("GET", "/workflow/" + wid + "?includeTasks=false"))
            if wf["status"] == "COMPLETED":
                break
            if wf["status"] not in ("RUNNING", "PAUSED"):
                fail("turn ended %s: %s" % (wf["status"], wf.get("reasonForIncompletion")))
            time.sleep(1)
        else:
            fail("turn did not complete within 150s")
        if (wf.get("input") or {}).get("model") != MODEL:
            fail("run input.model is %r, expected %r" % ((wf.get("input") or {}).get("model"), MODEL))
        after = definition()
        if before != after:
            fail("registered workflow definition changed after the run")
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

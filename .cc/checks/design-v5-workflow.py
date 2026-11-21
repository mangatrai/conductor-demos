import json, os, subprocess, sys, time, uuid, urllib.request

ROOT = os.path.join(os.getcwd(), "convo-agent")
API = os.environ.get("CONDUCTOR_SERVER_URL", "http://localhost:8080/api").rstrip("/")


def fail(msg):
    print("FAIL: " + msg)
    sys.exit(1)


def call(method, path, body=None, timeout=15):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def sh(*args, timeout=300):
    return subprocess.run(["./convo.sh", *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout)


if not os.path.isfile(os.path.join(ROOT, "convo.sh")):
    fail("convo-agent/convo.sh does not exist")

try:
    try:
        r = sh("start", "v5")
    except subprocess.TimeoutExpired:
        fail("./convo.sh start v5 did not finish in 300s")
    if r.returncode != 0:
        fail("./convo.sh start v5 exited %d: %s" % (r.returncode, (r.stderr or r.stdout).strip()[-200:]))
    sid = "chk-" + uuid.uuid4().hex[:8]
    try:
        wid = call("POST", "/workflow/convo_v5_agent_turn", {
            "sessionId": sid, "message": "Hello, what can you help me with?"}).strip().strip('"')
    except Exception as e:
        fail("could not start convo_v5_agent_turn: %s" % e)
    deadline = time.time() + 240
    wf = {}
    while time.time() < deadline:
        try:
            wf = json.loads(call("GET", "/workflow/" + wid))
        except Exception as e:
            fail("could not read execution %s: %s" % (wid, e))
        if wf.get("status") in ("COMPLETED", "FAILED", "TERMINATED", "TIMED_OUT"):
            break
        time.sleep(2)
    else:
        fail("execution %s still %s after 240s" % (wid, wf.get("status")))
    if wf["status"] != "COMPLETED":
        fail("execution ended %s: %s" % (wf["status"], wf.get("reasonForIncompletion")))
    out = wf.get("output") or {}
    reply = out.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        fail("output.reply empty: %r" % (out,))
    if out.get("agentMode") not in ("server", "local"):
        fail("agentMode is %r, expected server or local" % (out.get("agentMode"),))
    print("PASS")
finally:
    try:
        sh("stop", "v5", timeout=120)
    except Exception:
        pass

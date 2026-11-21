import json, os, subprocess, sys, time, uuid, urllib.request, urllib.error

ROOT = os.path.join(os.getcwd(), "convo-agent")
API = os.environ.get("CONDUCTOR_SERVER_URL", "http://localhost:8080/api").rstrip("/")
WF = "convo_v1_chat_turn"


def fail(msg):
    print("FAIL: " + msg)
    sys.exit(1)


def sh(*args, wait=300):
    try:
        return subprocess.run(list(args), cwd=ROOT, capture_output=True, text=True, timeout=wait)
    except Exception as e:
        fail("cannot run %s: %s" % (" ".join(args), e))


def http(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode()
    except Exception as e:
        fail("conductor request %s %s failed: %s" % (method, path, e))


def turn(session, prev, message):
    inp = {"sessionId": session, "prevExecutionId": prev, "message": message}
    if os.environ.get("CONVO_LLM_PROVIDER"):
        inp["llmProvider"] = os.environ["CONVO_LLM_PROVIDER"]
    if os.environ.get("CONVO_LLM_MODEL"):
        inp["model"] = os.environ["CONVO_LLM_MODEL"]
    wid = http("POST", "/workflow/%s?correlationId=%s" % (WF, session), inp).strip().strip('"')
    deadline = time.time() + 150
    while time.time() < deadline:
        run = json.loads(http("GET", "/workflow/%s?includeTasks=false" % wid))
        if run.get("status") in ("COMPLETED", "FAILED", "TERMINATED", "TIMED_OUT"):
            return run
        time.sleep(1)
    fail("workflow %s did not finish within 150s" % wid)


if not os.path.isfile(os.path.join(ROOT, "convo.sh")):
    fail("convo-agent/convo.sh does not exist")

r = sh("./convo.sh", "start", "v1")
try:
    if r.returncode != 0:
        fail("./convo.sh start v1 exited %d: %s" % (r.returncode, (r.stderr or r.stdout).strip()[-200:]))

    sa, sb = "chk-a-" + uuid.uuid4().hex[:8], "chk-b-" + uuid.uuid4().hex[:8]
    first = turn(sa, "", "Hello, my name is Sam.")
    if first.get("status") != "COMPLETED":
        fail("setup turn not COMPLETED: %s" % first.get("status"))
    foreign_id = first["output"]["executionId"] if "executionId" in first.get("output", {}) else first["workflowId"]

    cases = [("random prevExecutionId", sb, str(uuid.uuid4())),
             ("another session's executionId", sb, foreign_id)]
    for label, sess, prev in cases:
        run = turn(sess, prev, "What is a bond?")
        if run.get("status") != "COMPLETED":
            fail("%s: status %s (%s)" % (label, run.get("status"), run.get("reasonForIncompletion")))
        out = run.get("output") or {}
        if out.get("restored") is not False:
            fail("%s: restored=%r, expected false" % (label, out.get("restored")))
        hist = out.get("history")
        if not isinstance(hist, list) or len(hist) != 2:
            fail("%s: history length %s, expected 2" % (label, len(hist) if isinstance(hist, list) else hist))
finally:
    sh("./convo.sh", "stop", "v1", wait=60)
print("OK")

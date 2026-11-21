import json, os, socket, subprocess, sys, time, urllib.request, urllib.parse, uuid

ROOT = os.path.join(os.getcwd(), "convo-agent")
PY = "/Users/mrai/.uv/venvs/conductor/bin/python"
API = os.environ.get("CONDUCTOR_SERVER_URL", "http://localhost:8080/api").rstrip("/")


def fail(msg):
    print("FAIL: " + msg)
    sys.exit(1)


def call(method, path, body=None, timeout=15):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode()
    return raw


def hits():
    q = urllib.parse.quote('workflowType = "convo_v3_get_portfolio"')
    try:
        return json.loads(call("GET", "/workflow/search?size=1&query=" + q)).get("totalHits", 0)
    except Exception as e:
        fail("cannot query conductor: %s" % e)


if not os.path.isdir(ROOT):
    fail("convo-agent/ does not exist")

s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
env = dict(os.environ, MOCK_BASE_URL="http://localhost:%d" % port)
mock = None
try:
    mock = subprocess.Popen([PY, "-m", "v3.mock_api", "--port", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 20
    while time.time() < deadline:
        if mock.poll() is not None:
            fail("v3 mock_api exited early")
        try:
            socket.create_connection(("127.0.0.1", port), 1).close(); break
        except OSError:
            time.sleep(0.3)
    else:
        fail("mock api did not start")
    try:
        r = subprocess.run(["./convo.sh", "setup"], cwd=ROOT, env=env, capture_output=True, timeout=240)
    except Exception as e:
        fail("convo.sh setup: %s" % e)
    if r.returncode != 0:
        fail("convo.sh setup exit %d" % r.returncode)

    before = hits()
    sid = "chk-plain-" + uuid.uuid4().hex[:8]
    try:
        wid = call("POST", "/workflow/convo_v3_chat_turn", {
            "sessionId": sid, "prevExecutionId": "", "message": "What is a Roth IRA?",
            "llmProvider": os.environ.get("CONVO_LLM_PROVIDER", "ollama"),
            "model": os.environ.get("CONVO_LLM_MODEL", "qwen2.5:3b"),
            "systemPrompt": "You are a helpful wealth advisor assistant."}).strip().strip('"')
    except Exception as e:
        fail("cannot start convo_v3_chat_turn: %s" % e)
    deadline = time.time() + 180
    wf = None
    while time.time() < deadline:
        wf = json.loads(call("GET", "/workflow/" + wid + "?includeTasks=false"))
        if wf["status"] in ("COMPLETED", "FAILED", "TERMINATED", "TIMED_OUT"):
            break
        time.sleep(1)
    else:
        fail("turn did not finish in time")
    if wf["status"] != "COMPLETED":
        fail("turn status " + wf["status"])
    out = wf.get("output") or {}
    if "lookup" not in out or out["lookup"] is not None:
        fail("lookup not null: %r" % out.get("lookup", "<missing>"))
    if hits() != before:
        fail("a convo_v3_get_portfolio execution was started")
    print("PASS")
finally:
    if mock and mock.poll() is None:
        mock.terminate()
        try: mock.wait(5)
        except Exception: mock.kill()

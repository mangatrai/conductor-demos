import json, os, socket, subprocess, sys, time, urllib.request, urllib.error

ROOT = os.path.join(os.getcwd(), "convo-agent")
PY = "/Users/mrai/.uv/venvs/conductor/bin/python"
if not os.path.exists(PY):
    PY = sys.executable

def fail(msg):
    print("FAIL: " + msg)
    sys.exit(1)

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

if not os.path.isdir(ROOT):
    fail("convo-agent/ directory does not exist")

web, mock = free_port(), free_port()
env = dict(os.environ, MOCK_BASE_URL="http://localhost:%d" % mock)
procs = []
try:
    for args in (["-m", "v3.mock_api", "--port", str(mock)],
                 ["-m", "v2.server", "--version", "v3", "--port", str(web),
                  "--title", "Chat that does real work", "--static-dir", "v3/web"]):
        procs.append(subprocess.Popen([PY] + args, cwd=ROOT, env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    base = "http://127.0.0.1:%d" % web
    deadline = time.time() + 30
    while True:
        try:
            urllib.request.urlopen(base + "/healthz", timeout=2).read(); break
        except Exception as e:
            if time.time() > deadline:
                fail("v3 web did not start: %s" % e)
            time.sleep(0.5)
    body = json.dumps({"sessionId": "chk-v3-web", "prevExecutionId": "",
                       "message": "What's in Jane Doe's portfolio?"}).encode()
    req = urllib.request.Request(base + "/api/chat", body, {"Content-Type": "application/json"})
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=60).read())
    except Exception as e:
        fail("POST /api/chat failed: %s" % e)
    lk = data.get("lookup")
    if not isinstance(lk, dict) or not lk.get("subWorkflowId"):
        fail("response lacks lookup.subWorkflowId: %s" % str(data)[:200])
    if not data.get("uiUrl"):
        fail("response lacks uiUrl")
    try:
        page = urllib.request.urlopen(base + "/", timeout=10).read().decode()
    except Exception as e:
        fail("GET / failed: %s" % e)
    if "lookup-card" not in page:
        fail("page lacks lookup-card markup")
    print("OK")
finally:
    for p in procs:
        p.terminate()
    for p in procs:
        try: p.wait(5)
        except subprocess.TimeoutExpired: p.kill()

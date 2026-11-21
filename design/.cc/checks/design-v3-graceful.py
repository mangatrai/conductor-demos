#!/usr/bin/env python3
"""v3: unknown client -> not-found reply; mock API down -> unavailable reply; turn COMPLETED both times."""
import glob, json, os, re, socket, subprocess, sys, time, urllib.request, urllib.error

ROOT = os.getcwd()
APP = os.path.join(ROOT, "convo-agent")
VENV_PY = "/Users/mrai/.uv/venvs/conductor/bin/python"
PY = VENV_PY if os.path.exists(VENV_PY) else sys.executable
procs = []


def fail(msg):
    print("FAIL: " + msg.replace("\n", " ")[:300])
    cleanup()
    sys.exit(1)


def cleanup():
    for p in procs:
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
    procs.clear()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def http(method, url, body=None, timeout=10):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def start_mock(port, extra=()):
    p = subprocess.Popen([PY, "-m", "v3.mock_api", "--port", str(port), *extra], cwd=APP,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    end = time.time() + 20
    while time.time() < end:
        if p.poll() is not None:
            fail("mock_api exited at start-up")
        try:
            http("GET", f"http://127.0.0.1:{port}/healthz", timeout=2)
            return p
        except Exception:
            time.sleep(0.3)
    fail("mock_api did not answer /healthz in 20s")


def stop(p):
    p.terminate()
    try:
        p.wait(5)
    except subprocess.TimeoutExpired:
        p.kill()
    procs.remove(p)


def read_env(key, default):
    if key in os.environ:
        return os.environ[key]
    for f in (os.path.join(APP, ".env"), os.path.join(ROOT, ".env")):
        if os.path.exists(f):
            for line in open(f):
                line = line.strip()
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"\'')
    return default


def turn(api, msg, session):
    wid = http("POST", f"{api}/workflow/convo_v3_chat_turn?correlationId={session}",
               {"sessionId": session, "prevExecutionId": "", "message": msg}, 15).strip().strip('"')
    end = time.time() + 150
    while time.time() < end:
        wf = json.loads(http("GET", f"{api}/workflow/{wid}", timeout=10))
        if wf["status"] not in ("RUNNING", "PAUSED"):
            return wf
        time.sleep(1.5)
    fail("chat turn still running after 150s")


if not os.path.isdir(APP):
    fail("convo-agent/ does not exist")
wf_files = glob.glob(os.path.join(APP, "v3", "conductor", "workflows", "*.json"))
if not wf_files:
    fail("no v3 workflow definitions in convo-agent/v3/conductor/workflows")

api = read_env("CONDUCTOR_SERVER_URL", "http://localhost:8080/api").rstrip("/")
provider = read_env("CONVO_LLM_PROVIDER", "ollama")
model = read_env("CONVO_LLM_MODEL", "qwen2.5:3b")
mode_file = os.path.join(APP, ".run", "llm_mode")
worker_mode = os.path.exists(mode_file) and open(mode_file).read().strip() == "worker"

port = free_port()
try:
    http("GET", f"{api}/health", timeout=5)
except Exception as e:
    fail(f"conductor not reachable at {api}: {e}")

# register the v3 workflows pointing at THIS check's mock port
wfs = []
for f in sorted(wf_files):
    txt = open(f).read()
    txt = (txt.replace("{{LLM_PROVIDER}}", provider).replace("{{LLM_MODEL}}", model)
           .replace("{{MOCK_BASE_URL}}", f"http://localhost:{port}"))
    d = json.loads(txt)
    if worker_mode:
        def rw(o):
            if isinstance(o, dict):
                if o.get("type") == "LLM_CHAT_COMPLETE":
                    o["type"] = "SIMPLE"
                    o["name"] = "convo_llm_chat"
                for v in o.values():
                    rw(v)
            elif isinstance(o, list):
                for v in o:
                    rw(v)
        rw(d)
    wfs.append(d)
for tf in glob.glob(os.path.join(APP, "v3", "conductor", "tasks", "*.json")):
    try:
        http("POST", f"{api}/metadata/taskdefs", json.load(open(tf)))
    except Exception:
        pass
try:
    http("PUT", f"{api}/metadata/workflow", wfs)
except Exception as e:
    fail(f"could not register v3 workflows: {e}")

if worker_mode:
    w = subprocess.Popen([PY, "-m", "common.llm_worker"], cwd=APP, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(w)

try:
    sid = f"chk-v3-{int(time.time())}"
    # 1. unknown client
    m = start_mock(port)
    wf = turn(api, "What's in Zelda Quimby's portfolio?", sid + "-a")
    stop(m)
    if wf["status"] != "COMPLETED":
        fail(f"unknown-client turn status {wf['status']}")
    out = wf.get("output") or {}
    lk = out.get("lookup")
    if not isinstance(lk, dict) or lk.get("found") is not False:
        fail(f"unknown client: expected lookup.found=false, got {lk!r}")
    if not re.search(r"not found|couldn.t find|could not find|can.t find|cannot find|no (record|client|portfolio)|don.t (see|have|find)|unable to find|isn.t in|not in",
                     str(out.get("reply", "")), re.I):
        fail(f"unknown client: reply lacks not-found wording: {out.get('reply')!r}")

    # 2. mock API down
    m = start_mock(port, ["--fail"])
    wf = turn(api, "What's in Jane Doe's portfolio?", sid + "-b")
    stop(m)
    if wf["status"] != "COMPLETED":
        fail(f"api-down turn status {wf['status']}")
    out = wf.get("output") or {}
    lk = out.get("lookup")
    if not isinstance(lk, dict) or not lk.get("error"):
        fail(f"api down: expected lookup.error set, got {lk!r}")
    if not re.search(r"unavailable|not available|unable|temporar|can.t (access|reach|retrieve|get)|cannot (access|reach|retrieve)|trouble|issue|problem|down|error",
                     str(out.get("reply", "")), re.I):
        fail(f"api down: reply lacks unavailable wording: {out.get('reply')!r}")
finally:
    cleanup()
    # restore the canonical registration (best effort)
    try:
        subprocess.run([PY, "-c", "from common.register import register_version; register_version('v3')"],
                       cwd=APP, timeout=60, capture_output=True)
    except Exception:
        pass

print("OK: v3 unknown client and mock-down turns complete with graceful replies")

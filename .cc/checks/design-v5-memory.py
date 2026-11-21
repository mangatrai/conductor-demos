import json, os, re, subprocess, sys, time, urllib.parse, urllib.request, uuid

def fail(msg):
    print("FAIL: " + msg.replace("\n", " ")[:300]); sys.exit(1)

ROOT = os.getcwd()
APP = os.path.join(ROOT, "convo-agent")
if not os.path.isdir(APP):
    fail("convo-agent/ directory missing")
PY = "/Users/mrai/.uv/venvs/conductor/bin/python"
S = "chk-v5-mem-" + uuid.uuid4().hex[:8]
API = os.environ.get("CONDUCTOR_SERVER_URL", "http://localhost:8080/api").rstrip("/")

def chat(msg, prev=None):
    cmd = [PY, "-m", "v5.chat", "--session", S]
    if prev:
        cmd += ["--prev", prev]
    cmd.append(msg)
    try:
        p = subprocess.run(cmd, cwd=APP, capture_output=True, text=True, timeout=240)
    except subprocess.TimeoutExpired:
        fail("v5.chat timed out")
    if p.returncode != 0:
        fail("v5.chat exit %d: %s" % (p.returncode, (p.stderr or p.stdout)[-200:]))
    dec = json.JSONDecoder()
    out = p.stdout
    for m in re.finditer(r"\{", out):
        try:
            obj, _ = dec.raw_decode(out[m.start():])
            if isinstance(obj, dict) and "reply" in obj:
                return obj
        except ValueError:
            continue
    fail("no JSON reply in output: " + out[-200:])

r1 = chat("My client is 55, retiring at 62")
e1 = r1.get("executionId")
if not e1:
    fail("first reply has no executionId")
r2 = chat("How many years left?", prev=e1)
e2 = r2.get("executionId")
if not re.search(r"\b7\b|\bseven\b", str(r2.get("reply", "")), re.I):
    fail("second reply lacks 7/seven: %r" % str(r2.get("reply"))[:150])
if r2.get("restored") is not True:
    fail("second reply restored is not true: %r" % r2.get("restored"))
if not e2 or e2 == e1:
    fail("second executionId missing or same as first")

q = urllib.parse.urlencode({"query": 'correlationId="%s"' % S, "size": 50})
ids = set()
deadline = time.time() + 30
while time.time() < deadline:
    try:
        with urllib.request.urlopen(API + "/workflow/search?" + q, timeout=10) as r:
            d = json.load(r)
        ids = {x.get("workflowId") for x in d.get("results", [])}
    except Exception as e:
        fail("conductor search failed: %s" % e)
    if {e1, e2} <= ids:
        break
    time.sleep(1)
if not {e1, e2} <= ids:
    fail("correlation search for %s found %s, expected %s and %s" % (S, sorted(i for i in ids if i), e1, e2))
print("OK")

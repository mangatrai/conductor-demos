#!/usr/bin/env python3
"""v1: after 3 turns in one session, correlation search lists all 3 convo_v1_chat_turn runs."""
import json, os, subprocess, sys, time, urllib.parse, urllib.request

ROOT = os.getcwd()
APP = os.path.join(ROOT, "convo-agent")
PY = "/Users/mrai/.uv/venvs/conductor/bin/python"
API = os.environ.get("CONDUCTOR_SERVER_URL", "http://localhost:8080/api").rstrip("/")


def fail(msg):
    print("FAIL: " + msg.replace("\n", " ")[:300])
    sys.exit(1)


if not os.path.isdir(os.path.join(APP, "v1")):
    fail("convo-agent/v1 does not exist")
if not os.path.exists(PY):
    PY = sys.executable

try:
    urllib.request.urlopen(API + "/health", timeout=5).read()
except Exception as e:
    try:
        urllib.request.urlopen(API.rsplit("/api", 1)[0] + "/health", timeout=5).read()
    except Exception:
        fail("conductor not reachable at %s: %s" % (API, e))

env = dict(os.environ, CONDUCTOR_SERVER_URL=API)
reg = subprocess.run([PY, "-c", "from common.register import register_version; register_version('v1')"],
                     cwd=APP, env=env, capture_output=True, text=True, timeout=60)
if reg.returncode != 0:
    fail("register v1 failed: " + (reg.stderr.strip().splitlines() or ["?"])[-1])

session_file = os.path.join(APP, ".run", "v1_session.json")
if os.path.exists(session_file):
    os.remove(session_file)

msgs = "Hi, I am 55.\nI plan to retire at 62.\nHow many years is that?\n/quit\n"
try:
    p = subprocess.run([PY, "-m", "v1.chat"], cwd=APP, env=env, input=msgs,
                       capture_output=True, text=True, timeout=240)
except subprocess.TimeoutExpired:
    fail("v1.chat did not finish 3 turns within 240s")
if p.returncode != 0:
    fail("v1.chat exited %d: %s" % (p.returncode, (p.stderr.strip().splitlines() or ["?"])[-1]))

try:
    session_id = json.load(open(session_file))["sessionId"]
except Exception as e:
    fail("no sessionId saved in .run/v1_session.json: %s" % e)

q = urllib.parse.urlencode({"query": 'correlationId="%s"' % session_id, "size": 50})
deadline = time.time() + 30
found = []
while time.time() < deadline:
    try:
        res = json.load(urllib.request.urlopen(API + "/workflow/search?" + q, timeout=10))
    except Exception as e:
        fail("correlation search failed: %s" % e)
    found = [r for r in res.get("results", [])
             if r.get("workflowType") == "convo_v1_chat_turn" and r.get("correlationId") == session_id]
    if len(found) >= 3:
        break
    time.sleep(1)
ids = {r["workflowId"] for r in found}
if len(ids) != 3:
    fail("correlation search for %s listed %d convo_v1_chat_turn runs, expected 3" % (session_id, len(ids)))
print("OK: 3 executions listed for session " + session_id)

import json, os, subprocess, sys, uuid

PY = "/Users/mrai/.uv/venvs/conductor/bin/python"
APP = os.path.join(os.getcwd(), "convo-agent")


def fail(msg):
    print("FAIL: " + msg)
    sys.exit(1)


def turn(session, msg, prev=None):
    cmd = [PY, "-m", "v5.chat", "--session", session]
    if prev:
        cmd += ["--prev", prev]
    cmd.append(msg)
    try:
        p = subprocess.run(cmd, cwd=APP, capture_output=True, text=True, timeout=240)
    except subprocess.TimeoutExpired:
        fail("v5.chat timed out for session " + session)
    if p.returncode != 0:
        fail("v5.chat exit %d: %s" % (p.returncode, (p.stderr or p.stdout).strip()[-200:].replace("\n", " ")))
    out = p.stdout
    dec = json.JSONDecoder()
    found = None
    for i, ch in enumerate(out):
        if ch == "{":
            try:
                obj, _ = dec.raw_decode(out[i:])
            except ValueError:
                continue
            found = obj
            break
    if not isinstance(found, dict):
        fail("v5.chat printed no JSON object")
    return found


if not os.path.isdir(APP):
    fail("convo-agent/ does not exist")
tag = uuid.uuid4().hex[:8]
a = turn("chk-a-" + tag, "My client is 55, retiring at 62")
eid = a.get("executionId")
if not eid:
    fail("session A output has no executionId")
b = turn("chk-b-" + tag, "How many years left?", prev=eid)
if b.get("restored") is not False:
    fail("restored is %r, expected false" % (b.get("restored"),))
if b.get("memorySource") != "none":
    fail("memorySource is %r, expected 'none'" % (b.get("memorySource"),))
note = b.get("memoryNote")
if not isinstance(note, str) or not note.strip():
    fail("memoryNote is empty")
print("OK")

import os, re, subprocess, sys

PY = "/Users/mrai/.uv/venvs/conductor/bin/python"
APP = os.path.join(os.getcwd(), "convo-agent")


def fail(msg):
    print("FAIL: " + msg)
    sys.exit(1)


def chat(args, text):
    try:
        p = subprocess.run([PY, "-m", "v1.chat"] + args, cwd=APP, input=text,
                           capture_output=True, text=True, timeout=240)
    except subprocess.TimeoutExpired:
        fail("v1.chat did not finish within 240s")
    return p.returncode, p.stdout + p.stderr


if not os.path.isdir(os.path.join(APP, "v1")):
    fail("convo-agent/v1 does not exist")

rc, out = chat([], "I am 55 and plan to retire at 62.\nHow many years until I retire?\n/quit\n")
if rc != 0:
    fail("first v1.chat run exited %d: %s" % (rc, out[-200:].replace("\n", " ")))
if len(re.findall(r"execution:\s*https?://\S+", out)) < 2:
    fail("expected an execution link after each of the 2 replies")
if not re.search(r"session:\s*https?://\S+", out):
    fail("no session link printed")

rc, out = chat(["--resume"], "What age did I say I plan to retire at?\n/quit\n")
if rc != 0:
    fail("--resume run exited %d: %s" % (rc, out[-200:].replace("\n", " ")))
if "memory restored" not in out:
    fail("resumed run did not print 'memory restored'")
if not re.search(r"execution:\s*https?://\S+", out):
    fail("resumed turn printed no execution link")
print("OK")

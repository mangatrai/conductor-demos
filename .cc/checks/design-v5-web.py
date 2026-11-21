import json, os, socket, subprocess, sys, time, urllib.request, urllib.error

ROOT = os.path.join(os.getcwd(), "convo-agent")
PY = "/Users/mrai/.uv/venvs/conductor/bin/python"


def fail(msg):
    print("FAIL: " + msg)
    sys.exit(1)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


procs = []


def cleanup():
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()


def post(port, body):
    req = urllib.request.Request(
        "http://localhost:%d/api/chat" % port, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            return json.loads(r.read())
    except Exception as e:
        fail("POST /api/chat failed: %r" % (e,))


def main():
    if not os.path.isdir(ROOT):
        fail("convo-agent/ directory does not exist")
    web, worker = free_port(), free_port()
    env = dict(os.environ)
    try:
        subprocess.run(["./convo.sh", "setup", "v5"], cwd=ROOT, env=env, timeout=300,
                       capture_output=True)
        procs.append(subprocess.Popen([PY, "-m", "v5.worker", "--port", str(worker)], cwd=ROOT,
                                      env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        procs.append(subprocess.Popen(
            [PY, "-m", "v2.server", "--version", "v5", "--port", str(web), "--title",
             "Advisor as a Conductor Agent"], cwd=ROOT, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        deadline = time.time() + 60
        while True:
            try:
                urllib.request.urlopen("http://localhost:%d/healthz" % web, timeout=3).read()
                break
            except Exception:
                if time.time() > deadline:
                    fail("v5 web did not answer /healthz within 60s")
                time.sleep(1)
        sid = "check-v5-web-%d" % int(time.time())
        r1 = post(web, {"sessionId": sid, "message": "My client is 55, retiring at 62"})
        eid = r1.get("executionId")
        if not eid:
            fail("first response has no executionId: %r" % (r1,))
        r2 = post(web, {"sessionId": sid, "prevExecutionId": eid,
                        "message": "How many years left?"})
        if "7" not in str(r2.get("reply", "")):
            fail("second reply does not say 7: %r" % (r2.get("reply"),))
        if r2.get("restored") is not True:
            fail("restored is not true: %r" % (r2.get("restored"),))
        if not r2.get("uiUrl"):
            fail("uiUrl missing in second response")
    finally:
        cleanup()
    print("OK")


main()

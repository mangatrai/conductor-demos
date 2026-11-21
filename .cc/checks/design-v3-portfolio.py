#!/usr/bin/env python3
"""v3: portfolio question answers with mock numbers; history only user/assistant; get_portfolio returns holdings."""
import json, os, subprocess, sys, time, uuid, urllib.request, urllib.error

ROOT = os.path.join(os.getcwd(), "convo-agent")
API = os.environ.get("CONDUCTOR_SERVER_URL", "http://localhost:8080/api").rstrip("/")


def fail(msg):
    print("FAIL: " + msg)
    sys.exit(1)


def http(method, path, body=None, timeout=15):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode()
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def run_wf(name, inp, wait=150):
    try:
        wid = http("POST", "/workflow/" + name + "?correlationId=" + inp.get("sessionId", ""), inp)
    except Exception as e:
        fail("cannot start %s: %s" % (name, e))
    wid = wid.strip('"') if isinstance(wid, str) else wid
    deadline = time.time() + wait
    wf = {}
    while time.time() < deadline:
        try:
            wf = http("GET", "/workflow/%s?includeTasks=false" % wid)
        except Exception as e:
            fail("cannot read %s execution: %s" % (name, e))
        if wf.get("status") in ("COMPLETED", "FAILED", "TERMINATED", "TIMED_OUT"):
            return wf
        time.sleep(1)
    fail("%s still %s after %ss" % (name, wf.get("status"), wait))


def main():
    if not os.path.isfile(os.path.join(ROOT, "convo.sh")):
        fail("convo-agent/convo.sh does not exist")
    started = False
    try:
        try:
            p = subprocess.run(["bash", "./convo.sh", "start", "v3"], cwd=ROOT,
                               capture_output=True, text=True, timeout=240)
        except subprocess.TimeoutExpired:
            fail("./convo.sh start v3 did not finish in 240s")
        started = True
        if p.returncode != 0:
            fail("./convo.sh start v3 exit %d: %s" % (p.returncode, (p.stdout + p.stderr).strip()[-200:].replace("\n", " ")))

        sid = "chk-v3-" + uuid.uuid4().hex[:8]
        wf = run_wf("convo_v3_chat_turn", {"sessionId": sid, "prevExecutionId": "",
                                           "message": "What's in Jane Doe's portfolio?"})
        if wf.get("status") != "COMPLETED":
            fail("chat turn status %s: %s" % (wf.get("status"), wf.get("reasonForIncompletion")))
        out = wf.get("output") or {}
        reply = str(out.get("reply", ""))
        if "1,250,000" not in reply and "1.25" not in reply and "1250000" not in reply:
            fail("reply lacks Jane Doe total value 1,250,000: %r" % reply[:150])
        lk = out.get("lookup")
        if not isinstance(lk, dict) or not lk.get("subWorkflowId"):
            fail("output.lookup has no subWorkflowId: %r" % (lk,))
        try:
            sub = http("GET", "/workflow/%s?includeTasks=false" % lk["subWorkflowId"])
        except Exception as e:
            fail("subWorkflowId not readable: %s" % e)
        if sub.get("workflowName") != "convo_v3_get_portfolio":
            fail("subWorkflowId is a %s execution" % sub.get("workflowName"))
        hist = out.get("history")
        if not isinstance(hist, list) or len(hist) != 2 or [m.get("role") for m in hist] != ["user", "assistant"]:
            fail("history is not exactly user/assistant: %r" % (hist,))
        if "1250000" in json.dumps(hist[0]) or "holdings" in json.dumps(hist[0]) or "LOOKUP RESULT" in json.dumps(hist):
            fail("lookup data leaked into history")

        wf2 = run_wf("convo_v3_get_portfolio", {"clientName": "Jane Doe"}, wait=60)
        if wf2.get("status") != "COMPLETED":
            fail("get_portfolio status %s" % wf2.get("status"))
        o2 = wf2.get("output") or {}
        pf = o2.get("portfolio") or {}
        if o2.get("found") is not True:
            fail("get_portfolio found != true: %r" % (o2.get("found"),))
        if not pf.get("holdings"):
            fail("get_portfolio returned no holdings")
        if pf.get("totalValue") != 1250000:
            fail("get_portfolio totalValue %r != 1250000" % pf.get("totalValue"))
    finally:
        if started:
            try:
                subprocess.run(["bash", "./convo.sh", "stop", "v3"], cwd=ROOT,
                               capture_output=True, text=True, timeout=60)
            except Exception:
                pass
    print("OK")


main()

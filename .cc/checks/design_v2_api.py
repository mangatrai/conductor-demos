"""Acceptance check: v2 front door API (S5) driven with an in-file FakeConductor."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.getcwd()
APP = os.path.join(ROOT, "convo-agent")
CHECKS = os.path.join(ROOT, ".cc", "checks")


class FakeConductor:
    """Stand-in for common.conductor.Conductor, steered by the message text."""
    flavor = "oss"

    def __init__(self):
        self.runs = {}
        self.n = 0

    def _err(self):
        from common.conductor import ConductorError
        e = ConductorError("Conductor unreachable")
        e.status = 0
        e.path = "/workflow"
        e.body = ""
        return e

    def run_sync(self, name, input, correlation_id=None, wait_seconds=30):
        time.sleep(0.8)
        msg = input.get("message", "")
        if msg == "__down__":
            raise self._err()
        self.n += 1
        wid = "wf-%d" % self.n
        if name.endswith("chat_history"):
            prev = self.runs.get(input.get("executionId"))
            ok = bool(prev and prev["status"] == "COMPLETED"
                      and prev["input"].get("sessionId") == input.get("sessionId"))
            run = {"workflowId": wid, "status": "COMPLETED", "input": input,
                   "output": {"found": ok, "history": prev["output"]["history"] if ok else [],
                              "sessionId": input.get("sessionId")}}
            self.runs[wid] = run
            return run
        if msg == "__fail__":
            run = {"workflowId": wid, "status": "FAILED", "input": input, "output": {},
                   "reasonForIncompletion": "boom from fake"}
        elif msg == "__slow__":
            run = {"workflowId": wid, "status": "RUNNING", "input": input, "output": {}}
        else:
            prev = self.runs.get(input.get("prevExecutionId", ""))
            hist = []
            if prev and prev["status"] == "COMPLETED" and \
                    prev["input"].get("sessionId") == input.get("sessionId"):
                hist = list(prev["output"]["history"])
            reply = "echo[%s|%s]: %s" % (name, input.get("model", ""), msg)
            hist += [{"role": "user", "message": msg}, {"role": "assistant", "message": reply}]
            run = {"workflowId": wid, "status": "COMPLETED", "input": input,
                   "output": {"reply": reply, "history": hist, "executionId": wid,
                              "sessionId": input.get("sessionId"), "restored": bool(prev)}}
        self.runs[wid] = run
        return run

    def get_workflow(self, workflow_id, include_tasks=False):
        return {"workflowId": workflow_id, "status": "COMPLETED", "tasks": [
            {"referenceTaskName": r, "taskType": t, "status": "COMPLETED",
             "startTime": 1000, "endTime": 1000 + i * 10}
            for i, (r, t) in enumerate([("load_ref", "HTTP"), ("llm", "LLM_CHAT_COMPLETE"),
                                        ("answer", "JSON_JQ_TRANSFORM")], 1)]}

    def search_by_correlation(self, correlation_id, workflow_name=None, size=50):
        return []

    def start_workflow(self, name, input, correlation_id=None):
        return "wf-start"

    def ui_url(self, workflow_id=None, correlation_id=None):
        if workflow_id:
            return "http://localhost:5000/execution/%s" % workflow_id
        return "http://localhost:5000/executions?correlationId=%s" % correlation_id


def fail(msg):
    print("FAIL: " + msg)
    sys.exit(1)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def http(base, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        fail("request %s failed: %s" % (path, e))


def jhttp(base, path, body=None):
    code, raw = http(base, path, body)
    try:
        return code, json.loads(raw)
    except Exception:
        fail("%s did not return JSON (HTTP %s): %r" % (path, code, raw[:120]))


def start(args, port):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([APP, CHECKS])
    log = tempfile.TemporaryFile()
    cmd = [sys.executable, "-m", "v2.server", "--port", str(port),
           "--client", "design_v2_api:FakeConductor"] + args
    try:
        p = subprocess.Popen(cmd, cwd=APP, env=env, stdout=log, stderr=subprocess.STDOUT)
    except Exception as e:
        fail("cannot start server: %s" % e)
    base = "http://127.0.0.1:%d" % port
    deadline = time.time() + 25
    while time.time() < deadline:
        if p.poll() is not None:
            log.seek(0)
            fail("server exited early (%s): %s" % (p.returncode, log.read()[-200:].decode(errors="replace").replace("\n", " | ")))
        try:
            with urllib.request.urlopen(base + "/healthz", timeout=2) as r:
                if r.status == 200:
                    return p, base
        except Exception:
            time.sleep(0.3)
    p.kill()
    fail("server did not answer /healthz within 25s")


def stop(p):
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(5)
        except Exception:
            p.kill()


def turn(base, sid, msg, prev="", extra=None):
    body = {"sessionId": sid, "prevExecutionId": prev, "message": msg}
    body.update(extra or {})
    return jhttp(base, "/api/chat", body)


def main():
    if not os.path.isdir(APP):
        fail("convo-agent/ directory missing")
    procs = []
    try:
        p, base = start([], free_port())
        procs.append(p)
        code, h = jhttp(base, "/healthz")
        if code != 200 or h.get("ok") is not True:
            fail("/healthz not ok true: %s" % h)
        code, cfg = jhttp(base, "/api/config")
        if code != 200 or cfg.get("version") != "v2":
            fail("/api/config version not v2: %s" % cfg)
        for k in ("title", "features", "flavor", "llmProvider", "model"):
            if k not in cfg:
                fail("/api/config missing %s" % k)
        if not cfg["title"] or not isinstance(cfg["features"], list):
            fail("config title/features malformed: %s" % cfg)

        code, r1 = turn(base, "s1", "hello there")
        if code != 200:
            fail("chat turn HTTP %s: %s" % (code, r1))
        for k in ("reply", "history", "executionId", "uiUrl", "sessionUrl", "steps"):
            if k not in r1:
                fail("chat response missing %s: %s" % (k, sorted(r1)))
        if "convo_v2_chat_turn" not in r1["reply"]:
            fail("v2 did not run convo_v2_chat_turn: %s" % r1["reply"])
        if r1["executionId"] not in r1["uiUrl"] or "s1" not in r1["sessionUrl"]:
            fail("links do not point at execution/session: %s %s" % (r1["uiUrl"], r1["sessionUrl"]))
        st = r1["steps"]
        if not isinstance(st, list) or len(st) != 3 or not all(
                k in s for s in st for k in ("ref", "type", "status", "ms")):
            fail("steps malformed: %s" % st)
        if st[1]["ref"] != "llm" or st[1]["type"] != "LLM_CHAT_COMPLETE":
            fail("steps do not map ref/type: %s" % st[1])
        code, r2 = turn(base, "s1", "and again", prev=r1["executionId"], extra={"model": "m-x"})
        if code != 200 or len(r2["history"]) != 4 or "m-x" not in r2["reply"]:
            fail("second turn did not carry pointer/model: %s" % r2)

        for body, raw in (({"sessionId": "s1", "prevExecutionId": "", "message": ""}, None),
                          ({"sessionId": "s1", "message": "   "}, None),
                          ({"prevExecutionId": "", "message": "hi"}, None),
                          (None, b"not json")):
            c, rr = http(base, "/api/chat", body, raw)
            try:
                err = json.loads(rr).get("error")
            except Exception:
                err = None
            if c != 400 or not err:
                fail("bad body %s expected 400 with error, got %s %r" % (body, c, rr[:100]))

        c, e = turn(base, "s2", "__fail__")
        if c != 502 or not e.get("error") or "boom" not in e["error"]:
            fail("__fail__ expected 502 with reason, got %s %s" % (c, e))
        c, e = turn(base, "s2", "__down__")
        if c != 502 or not e.get("error"):
            fail("__down__ expected 502, got %s %s" % (c, e))
        c, e = turn(base, "s2", "__slow__")
        if c != 504 or not e.get("executionId"):
            fail("__slow__ expected 504 with executionId, got %s %s" % (c, e))

        q = "/api/session?sessionId=s1&executionId=" + r2["executionId"]
        c, s = jhttp(base, q)
        if c != 200 or s.get("found") is not True or len(s.get("history", [])) != 4:
            fail("session did not return stored history: %s %s" % (c, s))
        c, s = jhttp(base, "/api/session?sessionId=other&executionId=" + r2["executionId"])
        if c != 200 or s.get("found") is not False or s.get("history") != []:
            fail("foreign session should be found false: %s %s" % (c, s))
        c, _ = http(base, "/api/session?sessionId=s1")
        if c != 400:
            fail("session without executionId expected 400, got %s" % c)

        c, index_v2 = http(base, "/")
        if c != 200 or not index_v2:
            fail("v2 page not served at /")
        c, v2cfg = jhttp(base, "/api/config")

        tmp = tempfile.mkdtemp()
        starters = ["v3 starter alpha", "v3 starter beta"]
        with open(os.path.join(tmp, "starters.json"), "w") as f:
            json.dump(starters, f)
        p3, base3 = start(["--version", "v3", "--title", "V3 Title", "--static-dir", tmp], free_port())
        procs.append(p3)
        c, cfg3 = jhttp(base3, "/api/config")
        if cfg3.get("version") != "v3" or cfg3.get("title") != "V3 Title":
            fail("v3 config wrong: %s" % cfg3)
        if json.dumps(cfg3.get("starters")).count("v3 starter alpha") != 1:
            fail("v3 config does not carry v3 starters: %s" % cfg3.get("starters"))
        if cfg3.get("starters") == v2cfg.get("starters"):
            fail("v3 starters identical to v2 starters")
        c, r = turn(base3, "s9", "hi v3")
        if c != 200 or "convo_v3_chat_turn" not in r["reply"]:
            fail("v3 chat did not run convo_v3_chat_turn: %s %s" % (c, r))
        c, index_v3 = http(base3, "/")
        if c != 200 or index_v3 != index_v2:
            fail("v3 page is not v2's index.html")
        c, sj = http(base3, "/starters.json")
        if c != 200 or json.loads(sj) != starters:
            fail("v3 /starters.json not served from static dir")
        print("OK")
    finally:
        for p in procs:
            stop(p)


main()

import json, os, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

def fail(msg):
    print("FAIL: " + msg)
    sys.exit(1)

APP = os.path.join(os.getcwd(), "convo-agent")
if not os.path.isdir(APP):
    fail("convo-agent/ directory missing")
sys.path.insert(0, APP)

try:
    # ---- env precedence
    from common import config
    d = tempfile.mkdtemp()
    f1, f2 = os.path.join(d, "app.env"), os.path.join(d, "repo.env")
    open(f1, "w").write("CHK_A=app\nCHK_B=app\n# c\n")
    open(f2, "w").write("CHK_A=repo\nCHK_B=repo\nCHK_C='repo'\n")
    for k in ("CHK_A", "CHK_B", "CHK_C"):
        os.environ.pop(k, None)
    os.environ["CHK_A"] = "env"
    config.load([f1, f2])
    got = (os.environ.get("CHK_A"), os.environ.get("CHK_B"), os.environ.get("CHK_C"))
    if got != ("env", "app", "repo"):
        fail("env precedence wrong, got %r want ('env','app','repo')" % (got,))

    # ---- worker rewrite
    from common import register
    os.environ["CONVO_LLM_MODEL"] = "model-xyz"
    os.environ["CONVO_LLM_PROVIDER"] = "prov-xyz"
    ip = {"llmProvider": "{{LLM_PROVIDER}}", "model": "{{LLM_MODEL}}",
          "messages": [{"role": "user", "message": "hi"}], "temperature": 0.2, "maxTokens": 50}
    wf = {"name": "convo_x", "version": 1, "tasks": [
        {"name": "llm", "taskReferenceName": "llm_ref", "type": "LLM_CHAT_COMPLETE",
         "inputParameters": json.loads(json.dumps(ip))}]}
    orig = json.dumps(wf, sort_keys=True)
    out = register.prepare(wf, "worker", None)
    if json.dumps(wf, sort_keys=True) != orig:
        fail("prepare mutated its argument")
    t = out["tasks"][0]
    if t.get("type") != "SIMPLE" or t.get("name") != "convo_llm_chat":
        fail("task not rewritten to SIMPLE convo_llm_chat: %r" % t)
    if t.get("taskReferenceName") != "llm_ref":
        fail("taskReferenceName changed")
    p = t.get("inputParameters", {})
    if p.get("model") != "model-xyz" or "{{" in json.dumps(out):
        fail("model placeholder not replaced: %r" % p.get("model"))
    for k in ("messages", "temperature", "maxTokens"):
        if p.get(k) != ip[k]:
            fail("inputParameters.%s changed" % k)

    # ---- worker json output
    from common import llm_worker
    state = {"content": '{"intent": "lookup", "n": 3}'}
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            body = json.dumps({"model": "m", "message": {"role": "assistant", "content": state["content"]}, "done": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["OLLAMA_URL"] = "http://127.0.0.1:%d" % srv.server_address[1]
    base = {"model": "m", "messages": [{"role": "user", "message": "x"}], "temperature": 0, "maxTokens": 20}
    r = llm_worker.chat(dict(base, jsonOutput=True))
    if r.get("result") != {"intent": "lookup", "n": 3}:
        fail("jsonOutput true did not return parsed JSON: %r" % (r,))
    state["content"] = "not json at all"
    r = llm_worker.chat(dict(base, jsonOutput=True))
    if r.get("result") != "not json at all":
        fail("unparseable output should be raw string: %r" % (r,))
    srv.shutdown()
except SystemExit:
    raise
except BaseException as e:
    fail("%s: %s" % (type(e).__name__, e))
print("OK")

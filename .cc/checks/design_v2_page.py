"""v2 chat page behaviour, driven in a browser against the front door with a fake Conductor."""
import http.server
import os
import socket
import subprocess
import sys
import tempfile
import threading
import json

ROOT = os.path.join(os.getcwd(), "convo-agent")
PY = "/Users/mrai/.uv/venvs/conductor/bin/python"

FAKE = r'''
import time

class FakeConductor:
    flavor = "oss"
    def __init__(self):
        self.runs = {}
        self.n = 0
    def run_sync(self, name, input, correlation_id=None, wait_seconds=30):
        time.sleep(0.8)
        self.n += 1
        wid = "wf-%d" % self.n
        if name.endswith("chat_history"):
            prev = self.runs.get(input.get("executionId"))
            ok = bool(prev and prev["input"].get("sessionId") == input.get("sessionId"))
            out = {"found": ok, "history": prev["output"]["history"] if ok else [], "sessionId": input.get("sessionId")}
            return {"workflowId": wid, "status": "COMPLETED", "output": out, "input": input}
        msg = input.get("message", "")
        if msg == "__fail__":
            return {"workflowId": wid, "status": "FAILED", "output": {}, "input": input,
                    "reasonForIncompletion": "boom"}
        prev = self.runs.get(input.get("prevExecutionId"))
        hist = list(prev["output"]["history"]) if prev else []
        hist += [{"role": "user", "message": msg}, {"role": "assistant", "message": "echo: " + msg}]
        out = {"reply": "echo: " + msg, "history": hist, "executionId": wid}
        run = {"workflowId": wid, "status": "COMPLETED", "output": out, "input": input}
        self.runs[wid] = run
        return run
    def get_workflow(self, workflow_id, include_tasks=False):
        t = [("build_ref", "JSON_JQ_TRANSFORM"), ("chat_ref", "LLM_CHAT_COMPLETE"), ("save_ref", "JSON_JQ_TRANSFORM")]
        return {"workflowId": workflow_id, "status": "COMPLETED", "tasks": [
            {"referenceTaskName": r, "taskType": ty, "status": "COMPLETED", "startTime": 1000, "endTime": 1042}
            for r, ty in t]}
    def search_by_correlation(self, correlation_id, workflow_name=None, size=50):
        return []
    def ui_url(self, workflow_id=None, correlation_id=None):
        if workflow_id:
            return "http://localhost:5000/execution/" + workflow_id
        return "http://localhost:5000/workflowDefs?correlationId=" + str(correlation_id)
'''

def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p

class Tags(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"models": [{"name": "qwen2.5:3b"}, {"name": "other-model:1b"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass

SCEN = r'''
const { scenario } = await import(process.env.PLAYWRIGHT_SCENARIO);
const PORT = __PORT__;
const T = { timeout: 8000 };
function ok(c, m) { if (!c) throw new Error(m); }
await scenario(async ({ page }) => {
  const chats = [];
  page.on('request', r => { if (r.url().includes('/api/chat') && r.method() === 'POST') chats.push(JSON.parse(r.postData() || '{}')); });
  const stored = () => page.evaluate(() => { const k = Object.keys(localStorage).find(x => x.startsWith('convo:')); return k ? JSON.parse(localStorage[k]) : null; });
  const send = async (text) => { await page.locator('#input').fill(text); await page.locator('#send').click(); };

  await page.goto(`http://127.0.0.1:${PORT}/`);
  await page.locator('#starters .starter').first().waitFor(T);

  // typing state
  await send('hello there');
  await page.locator('#typing').waitFor({ state: 'visible', ...T });
  ok(await page.locator('#send').isDisabled(), 'Send not disabled while the turn is in flight');
  await page.locator('.msg.bot').first().waitFor(T);
  await page.locator('#typing').waitFor({ state: 'hidden', ...T });
  ok(await page.locator('#send').isEnabled(), 'Send not re-enabled after the reply');

  // links and steps
  await page.locator('#exec-link').waitFor({ state: 'visible', ...T });
  await page.locator('#session-link').waitFor({ state: 'visible', ...T });
  ok((await page.locator('#exec-link').getAttribute('href')).includes('wf-'), 'exec link does not point at the execution');
  const steps = page.locator('.steps').first();
  await steps.waitFor(T);
  await steps.locator('summary').click();
  const st = await steps.innerText();
  ok(st.includes('LLM_CHAT_COMPLETE') && st.includes('chat_ref'), 'steps panel lacks task ref/type: ' + st);
  ok(/\d+\s*ms/.test(st), 'steps panel lacks the time: ' + st);
  const s1 = await stored();
  ok(s1 && s1.executionId, 'executionId not stored after success');

  // failed turn
  await send('__fail__');
  await page.locator('.msg.error').waitFor(T);
  await page.locator('#send').waitFor({ state: 'visible', ...T });
  ok(await page.locator('#send').isEnabled(), 'Send not re-enabled after a failure');
  await page.locator('.msg.error').getByRole('button', { name: /retry/i }).waitFor(T);
  const s2 = await stored();
  ok(s2.executionId === s1.executionId, `executionId changed after failure: ${s1.executionId} -> ${s2.executionId}`);
  ok(chats[chats.length - 1].prevExecutionId === s1.executionId, 'failed turn did not carry the old pointer');

  // resume
  await page.reload();
  await page.locator('#resume-banner').waitFor({ state: 'visible', ...T });
  ok((await page.locator('#resume-banner').innerText()).includes('You left off here. Continue?'), 'banner text wrong');
  await page.locator('#resume-continue').click();
  await page.locator('#resume-banner').waitFor({ state: 'hidden', ...T });
  await page.locator('.msg.user', { hasText: 'hello there' }).first().waitFor(T);
  await page.locator('.msg.bot', { hasText: 'echo: hello there' }).first().waitFor(T);

  // new chat
  const firstSession = s1.sessionId;
  ok(firstSession, 'sessionId not stored');
  await page.locator('#new-chat').click();
  await page.locator('.msg').first().waitFor({ state: 'detached', ...T }).catch(() => {});
  ok(await page.locator('#messages .msg').count() === 0, 'messages not cleared by New chat');
  await page.locator('#starters .starter').first().waitFor({ state: 'visible', ...T });
  const before = chats.length;
  await send('fresh start');
  await page.locator('.msg.bot', { hasText: 'echo: fresh start' }).waitFor(T);
  const c = chats[before];
  ok(c.sessionId && c.sessionId !== firstSession, 'next turn did not use a new sessionId');
  ok(!c.prevExecutionId, 'next turn after New chat carried a pointer: ' + c.prevExecutionId);

  // model picker + starter
  await page.locator('#new-chat').click();
  const opts = await page.locator('#model option').evaluateAll(o => o.map(x => x.value));
  ok(opts.length >= 2, 'model picker has fewer than two options: ' + opts);
  const chosen = opts.find(o => o !== opts[0]);
  await page.locator('#model').selectOption(chosen);
  const starter = page.locator('#starters .starter').first();
  await starter.waitFor({ state: 'visible', ...T });
  const text = (await starter.innerText()).trim();
  const b2 = chats.length;
  await starter.click();
  await page.locator('.msg.bot').first().waitFor(T);
  const d = chats[b2];
  ok(d && d.message.trim() === text, `starter text not sent: ${d && d.message} vs ${text}`);
  ok(d.model === chosen, `request model ${d.model} != chosen ${chosen}`);
});
'''

def main():
    if not os.path.isdir(ROOT):
        print("FAIL: convo-agent/ does not exist")
        return 1
    port = free_port()
    tags = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Tags)
    threading.Thread(target=tags.serve_forever, daemon=True).start()
    tmp = tempfile.mkdtemp()
    open(os.path.join(tmp, "v2_page_fake.py"), "w").write(FAKE)
    scen = os.path.join(tmp, "scen.mjs")
    open(scen, "w").write(SCEN.replace("__PORT__", str(port)).replace(
        "await scenario(async", "await scenario(async", 1).replace(
        "});\n'''", "});"))
    # add start/url options to the scenario call
    src = open(scen).read().rstrip()
    assert src.endswith("});")
    src = src[:-3] + "}, { start: %s, env: %s, url: 'http://127.0.0.1:%d/healthz' });\n" % (
        json.dumps([PY, "-m", "v2.server", "--version", "v2", "--port", str(port),
                    "--client", "v2_page_fake:FakeConductor"]),
        json.dumps({"PYTHONPATH": ROOT + os.pathsep + tmp,
                    "OLLAMA_URL": "http://127.0.0.1:%d" % tags.server_address[1]}),
        port)
    open(scen, "w").write(src)
    try:
        r = subprocess.run(["node", scen], cwd=ROOT, capture_output=True, text=True, timeout=150)
    except subprocess.TimeoutExpired:
        print("FAIL: page scenario timed out")
        return 1
    finally:
        tags.shutdown()
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip().splitlines()
        print("FAIL: " + (msg[0] if msg else "scenario failed")[:300])
        return 1
    print("ok")
    return 0

sys.exit(main())

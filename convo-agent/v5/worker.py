"""python -m v5.worker --port 8751: runs SIMPLE task convo_v5_agent_run (the local agent) + GET /healthz.

On start it probes the server and registers the right convo_v5_agent_turn variant (v5.probe --write).
"""
import argparse
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from common import config
from v5 import probe
from v5.turn import run_agent

TASK = "convo_v5_agent_run"
_started = []


def execute(task_input):
    """Task input {message, history, ...} -> {reply, toolCalls, agentMode: "local"}."""
    return run_agent(task_input.get("message") or "", task_input.get("history") or [])


def _loop(api, worker_id):
    while True:
        try:
            r = requests.get("%s/tasks/poll/%s" % (api, TASK), params={"workerid": worker_id}, timeout=30)
            if r.status_code != 200 or not r.content:
                time.sleep(0.2)
                continue
            task = r.json()
        except (requests.RequestException, ValueError):
            time.sleep(2)
            continue
        result = {"workflowInstanceId": task["workflowInstanceId"], "taskId": task["taskId"], "workerId": worker_id}
        try:
            result.update(status="COMPLETED", outputData=execute(task.get("inputData") or {}))
        except Exception as e:  # the workflow FAILS with the reason; never a reply that pretends
            result.update(status="FAILED", reasonForIncompletion="agent run failed: %s: %s" % (type(e).__name__, e))
        for _ in range(3):
            try:
                requests.post(api + "/tasks", json=result, timeout=15).raise_for_status()
                break
            except requests.RequestException:
                time.sleep(1)


def start_polling(threads=1):
    """Poll convo_v5_agent_run in daemon threads (once per process)."""
    if _started:
        return
    api = config.get("CONDUCTOR_SERVER_URL").rstrip("/")
    for i in range(threads):
        t = threading.Thread(target=_loop, args=(api, "%s-v5-%d" % (socket.gethostname(), i)), daemon=True)
        t.start()
        _started.append(t)


def _keep_variant(report):
    """`convo.sh start` re-registers the AGENT file while this worker runs; put the local variant back."""
    from common.conductor import Conductor
    c = Conductor()
    while not report.get("agentTask"):
        time.sleep(5)
        try:
            wf = c._req("GET", "/metadata/workflow/convo_v5_agent_turn")
            if any(t.get("type") == "AGENT" for t in (wf or {}).get("tasks", [])):
                probe.write(c, report)
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8751)
    args = ap.parse_args()
    report = probe.ensure()
    start_polling(threads=2)
    threading.Thread(target=_keep_variant, args=(report,), daemon=True).start()

    class Health(BaseHTTPRequestHandler):
        def do_GET(self):
            ok = self.path.split("?")[0] == "/healthz"
            body = json.dumps({"ok": True, "task": TASK, "agentMode": report.get("agentMode")} if ok
                              else {"error": "not found"}).encode()
            self.send_response(200 if ok else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    print("v5 worker: %s on port %d (agentMode %s)" % (TASK, args.port, report.get("agentMode")), flush=True)
    try:
        ThreadingHTTPServer(("127.0.0.1", args.port), Health).serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

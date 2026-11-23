"""S5: the web chat front door - a local stand-in for the Orkes API Gateway.

    python -m v2.server --version v2 --port 8720 [--title T] [--static-dir DIR] [--client mod:Class]

It serves the chat page and turns each HTTP call into one synchronous workflow run:
    POST /api/chat     -> convo_<version>_chat_turn
    GET  /api/session  -> convo_<version>_chat_history
Any version can reuse it (v3, v5 ...) by passing its own --version.
"""
import argparse
import importlib
import json
import logging
import os
import time

import requests
import uvicorn
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse

from common import APP_DIR, config

V2_WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
log = logging.getLogger("convo.front_door")


def load_client(spec="common.conductor:Conductor"):
    """`module:Class` -> instance. Imported lazily so tests can inject a fake Conductor."""
    mod, _, cls = spec.partition(":")
    return getattr(importlib.import_module(mod), cls or "Conductor")()


def _read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _err(status, msg, **extra):
    return JSONResponse({"error": msg, **extra}, status_code=status)


def _ollama_models(current):
    try:
        tags = requests.get(config.get("OLLAMA_URL").rstrip("/") + "/api/tags", timeout=1).json()
        names = [m["name"] for m in tags.get("models", []) if m.get("name")]
    except Exception:
        names = []
    return [current] + [n for n in names if n != current]


def _steps(client, workflow_id):
    """The 'what Conductor did' panel: one row per task. Never fails the turn."""
    try:
        tasks = client.get_workflow(workflow_id, include_tasks=True).get("tasks") or []
        return [{"ref": t.get("referenceTaskName"), "type": t.get("taskType"), "status": t.get("status"),
                 "ms": max(0, (t.get("endTime") or 0) - (t.get("startTime") or 0))} for t in tasks]
    except Exception:
        return []


def _conductor_error(e):
    return "Conductor unreachable" if getattr(e, "status", None) == 0 else str(e) or "Conductor error"


def create_app(version="v2", title=None, static_dir=None, client=None):
    client = client or load_client()
    manifest = _read_json(os.path.join(APP_DIR, version, "manifest.json"), {})
    title = title or manifest.get("title") or "Wealth advisor chat (%s)" % version
    features = manifest.get("features") or []
    turn_wf, history_wf = "convo_%s_chat_turn" % version, "convo_%s_chat_history" % version
    dirs = [d for d in (static_dir, V2_WEB) if d]

    def static_file(name):
        for d in dirs:  # per-file fallback: a version may override only starters.json or style.css
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
        return None

    app = FastAPI(title=title)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/api/config")
    def api_config():
        model = config.get("CONVO_LLM_MODEL")
        try:
            ui = client.ui_url()
        except Exception:
            ui = ""
        return {"version": version, "title": title, "features": features,
                "flavor": getattr(client, "flavor", "oss"), "conductorUiUrl": ui,
                "llmProvider": config.get("CONVO_LLM_PROVIDER"), "model": model,
                "starters": _read_json(static_file("starters.json") or "", []),
                "models": _ollama_models(model)}

    def run_turn(body):
        sid = body["sessionId"]
        t0 = time.time()
        try:
            run = client.run_sync(turn_wf, body, correlation_id=sid, wait_seconds=30)
        except Exception as e:
            log.warning("turn session=%s conductor error: %s", sid, e)
            return _err(502, _conductor_error(e))
        wid, status = run.get("workflowId", ""), run.get("status")
        ms = int((time.time() - t0) * 1000)
        log.warning("turn session=%s executionId=%s status=%s ms=%d", sid, wid, status, ms)
        if status == "COMPLETED":
            out = dict(run.get("output") or {})
            out.setdefault("executionId", wid)
            out.update(uiUrl=client.ui_url(workflow_id=wid), sessionUrl=client.ui_url(correlation_id=sid),
                       elapsedMs=ms, steps=_steps(client, wid))
            return JSONResponse(out)
        if status in ("RUNNING", "PAUSED"):
            return _err(504, "still running after 30 s - open the execution in Conductor", executionId=wid)
        return _err(502, run.get("reasonForIncompletion") or "workflow %s" % status, executionId=wid)

    @app.post("/api/chat")
    async def api_chat(request: Request):
        try:
            body = json.loads(await request.body())
        except ValueError:
            return _err(400, "body must be JSON")
        if not isinstance(body, dict):
            return _err(400, "body must be a JSON object")
        sid, msg, prev = body.get("sessionId"), body.get("message"), body.get("prevExecutionId", "")
        if not isinstance(sid, str) or not sid.strip() or len(sid) > 100:
            return _err(400, "sessionId must be a non-empty string (max 100 chars)")
        if not isinstance(msg, str) or not msg.strip() or len(msg.strip()) > 4000:
            return _err(400, "message must be a non-empty string (max 4000 chars)")
        if prev is None:
            prev = ""
        if not isinstance(prev, str):
            return _err(400, "prevExecutionId must be a string")
        inp = {"sessionId": sid, "prevExecutionId": prev, "message": msg.strip()}
        for k in ("llmProvider", "model"):  # omitted -> the workflow's own defaults apply
            v = body.get(k)
            if v is not None and not isinstance(v, str):
                return _err(400, "%s must be a string" % k)
            if v:
                inp[k] = v
        return await run_in_threadpool(run_turn, inp)

    @app.get("/api/session")
    def api_session(sessionId: str = "", executionId: str = ""):
        if not sessionId or not executionId:
            return _err(400, "sessionId and executionId are required")
        try:
            run = client.run_sync(history_wf, {"executionId": executionId, "sessionId": sessionId},
                                  correlation_id=sessionId, wait_seconds=30)
        except Exception as e:
            return _err(502, _conductor_error(e))
        if run.get("status") != "COMPLETED":
            return _err(502, run.get("reasonForIncompletion") or "history lookup %s" % run.get("status"),
                        executionId=run.get("workflowId"))
        out = dict(run.get("output") or {"found": False, "history": [], "sessionId": sessionId})
        if out.get("found"):
            out.update(uiUrl=client.ui_url(workflow_id=executionId), sessionUrl=client.ui_url(correlation_id=sessionId))
        return out

    @app.get("/")
    def index():
        return FileResponse(static_file("index.html"))

    @app.get("/{name}")
    def static(name: str):
        p = static_file(name)
        if not p:
            return _err(404, "not found")
        return FileResponse(p, headers={"Cache-Control": "no-cache"})

    return app


def main(argv=None):
    ap = argparse.ArgumentParser(description="Web chat front door (local stand-in for the Orkes API Gateway)")
    ap.add_argument("--version", default="v2")
    ap.add_argument("--port", type=int, default=8720)
    ap.add_argument("--title")
    ap.add_argument("--static-dir")
    ap.add_argument("--client", default="common.conductor:Conductor")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    static_dir = a.static_dir
    if static_dir and not os.path.isabs(static_dir):
        static_dir = os.path.join(APP_DIR, static_dir)
    app = create_app(a.version, a.title, static_dir, load_client(a.client))
    print("%s front door on http://localhost:%d/" % (a.version, a.port), flush=True)
    uvicorn.run(app, host="0.0.0.0", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()

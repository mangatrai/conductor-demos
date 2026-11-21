"""S2: load a version's Conductor JSON, fill placeholders, adapt to the LLM mode, register."""
import copy
import glob
import json
import os

from common import APP_DIR, config, llm_mode
from common.conductor import Conductor

NESTED = ("decisionCases", "defaultCase", "forkTasks", "loopOver")


def _placeholders(mock_port):
    vals = {
        "{{LLM_PROVIDER}}": config.get("CONVO_LLM_PROVIDER"),
        "{{LLM_MODEL}}": config.get("CONVO_LLM_MODEL"),
        "{{CONDUCTOR_API}}": config.get("CONDUCTOR_SERVER_URL").rstrip("/"),
    }
    if mock_port:
        vals["{{MOCK_BASE_URL}}"] = "http://localhost:%s" % mock_port
    return vals


def _fill(obj, vals):
    if isinstance(obj, str):
        for k, v in vals.items():
            obj = obj.replace(k, v)
        return obj
    if isinstance(obj, list):
        return [_fill(x, vals) for x in obj]
    if isinstance(obj, dict):
        return {k: _fill(v, vals) for k, v in obj.items()}
    return obj


def _walk(tasks, fn):
    for t in tasks or []:
        fn(t)
        for key in NESTED:
            v = t.get(key)
            if isinstance(v, dict):  # decisionCases
                for branch in v.values():
                    _walk(branch, fn)
            elif isinstance(v, list) and v and isinstance(v[0], list):  # forkTasks
                for branch in v:
                    _walk(branch, fn)
            elif isinstance(v, list):  # defaultCase / loopOver
                _walk(v, fn)


def prepare(wf, mode, mock_port=None, get_workflow_ok=True):
    """Pure: returns a deep copy of wf ready to register. Never mutates wf."""
    out = _fill(copy.deepcopy(wf), _placeholders(mock_port))
    api = config.get("CONDUCTOR_SERVER_URL").rstrip("/")

    def fix(t):
        if mode == "worker" and t.get("type") == "LLM_CHAT_COMPLETE":
            t["type"] = "SIMPLE"
            t["name"] = "convo_llm_chat"
        if not get_workflow_ok and t.get("type") == "GET_WORKFLOW":
            wid = (t.get("inputParameters") or {}).get("workflowId", "${workflow.input.prevExecutionId}")
            t["type"] = "HTTP"
            t["optional"] = True
            t["inputParameters"] = {"http_request": {
                "uri": "%s/workflow/%s?includeTasks=false" % (api, wid),
                "method": "GET", "accept": "application/json",
                "connectionTimeOut": 3000, "readTimeOut": 5000}}

    _walk(out.get("tasks"), fix)
    return out


def _load_json_files(pattern):
    items = []
    for f in sorted(glob.glob(pattern)):
        data = json.load(open(f))
        items.extend(data if isinstance(data, list) else [data])
    return items


def register_common(client=None):
    client = client or Conductor()
    defs = _load_json_files(os.path.join(APP_DIR, "common", "tasks", "*.json"))
    client.register_task_defs(defs)
    return [d["name"] for d in defs]


def register_version(v, client=None):
    client = client or Conductor()
    vdir = os.path.join(APP_DIR, v)
    manifest = {}
    try:
        manifest = json.load(open(os.path.join(vdir, "manifest.json")))
    except (OSError, ValueError):
        pass
    mode, gw_ok = llm_mode.effective_mode(), llm_mode.get_workflow_ok()
    port = manifest.get("mock_base_url_port")
    defs = _load_json_files(os.path.join(vdir, "conductor", "tasks", "*.json"))
    defs = [_fill(d, _placeholders(port)) for d in defs]
    client.register_task_defs(defs)
    names = [d["name"] for d in defs]
    for wf in _load_json_files(os.path.join(vdir, "conductor", "workflows", "*.json")):
        client.register_workflow(prepare(wf, mode, port, gw_ok))
        names.append(wf["name"])
    return names

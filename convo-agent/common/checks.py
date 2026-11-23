"""Step-0 checks: probe what this Conductor + Ollama can do; write .run/checks.json and .run/llm_mode."""
import json
import os
import sys
import time
import uuid

from common import RUN_DIR, config, ollama
from common.conductor import Conductor, ConductorError


def _wf(name, tasks, output=None):
    return {"name": name, "version": 1, "schemaVersion": 2, "ownerEmail": "convo-agent@example.com",
            "timeoutSeconds": 120, "timeoutPolicy": "TIME_OUT_WF", "tasks": tasks, "outputParameters": output or {}}


def _jq(ref, query, **params):
    return {"name": ref, "taskReferenceName": ref, "type": "JSON_JQ_TRANSFORM",
            "inputParameters": dict(params, queryExpression=query)}


def _run(c, wf, inp, wait=20):
    """Run wf; a task still SCHEDULED after 4 s means this server does not know that system task
    (OSS queues unknown task types like SIMPLE tasks), so stop early and report it."""
    c.register_workflow(wf)
    wid = c.start_workflow(wf["name"], inp)
    t0 = time.time()
    while True:
        run = c.get_workflow(wid, include_tasks=True)
        run.setdefault("workflowId", wid)
        if run.get("status") in ("COMPLETED", "FAILED", "TERMINATED", "TIMED_OUT"):
            return run
        stuck = [t for t in run.get("tasks") or [] if t.get("status") == "SCHEDULED"]
        if time.time() - t0 > wait or (stuck and time.time() - t0 > 4):
            c.terminate(wid)
            if stuck:
                run["reasonForIncompletion"] = "task type %s not supported (stayed SCHEDULED)" % stuck[0].get("taskType")
            return run
        time.sleep(0.25)


def probe_llm(c):
    wf = _wf("convo_platform_probe_llm", [{
        "name": "llm", "taskReferenceName": "llm_ref", "type": "LLM_CHAT_COMPLETE",
        "inputParameters": {"llmProvider": config.get("CONVO_LLM_PROVIDER"), "model": config.get("CONVO_LLM_MODEL"),
                            "messages": [{"role": "user", "message": "Reply with the single word: pong"}],
                            "temperature": 0, "maxTokens": 10}}], {"result": "${llm_ref.output.result}"})
    try:
        run = _run(c, wf, {}, wait=45)
    except ConductorError as e:
        return {"ok": False, "reason": "register/run failed: %s" % str(e)[:200]}
    res = (run.get("output") or {}).get("result")
    if run.get("status") == "COMPLETED" and res:
        return {"ok": True, "reason": "native LLM_CHAT_COMPLETE answered"}
    return {"ok": False, "reason": "status %s: %s" % (run.get("status"), (run.get("reasonForIncompletion") or "empty result")[:200])}


def probe_get_workflow(c):
    marker = "probe-" + uuid.uuid4().hex[:8]
    try:
        src = _run(c, _wf("convo_platform_probe_echo", [_jq("echo_ref", "{m: .m}", m="${workflow.input.m}")],
                          {"m": "${echo_ref.output.result.m}"}), {"m": marker})
        wf = _wf("convo_platform_probe_getwf", [{
            "name": "get_wf", "taskReferenceName": "load_prev_ref", "type": "GET_WORKFLOW", "optional": True,
            "inputParameters": {"workflowId": "${workflow.input.id}", "includeTasks": False}}],
            {"prev": "${load_prev_ref.output}"})
        ok_run = _run(c, wf, {"id": src["workflowId"]})
        if ok_run.get("status") != "COMPLETED" and "not supported" in (ok_run.get("reasonForIncompletion") or ""):
            r = ok_run["reasonForIncompletion"]
            return {"ok": False, "reason": r}, {"ok": False, "task_status": None, "reason": r}
        ok = ok_run.get("status") == "COMPLETED" and marker in json.dumps(ok_run.get("output"))
        good = {"ok": ok, "reason": "GET_WORKFLOW output contains the earlier run" if ok else
                "status %s, output lacks earlier run" % ok_run.get("status")}
        miss = _run(c, wf, {"id": "00000000-0000-0000-0000-000000000000"})
        tasks = c.get_workflow(miss["workflowId"], include_tasks=True).get("tasks") or []
        missing = {"ok": miss.get("status") == "COMPLETED",
                   "task_status": tasks[0].get("status") if tasks else None}
        return good, missing
    except ConductorError as e:
        r = "GET_WORKFLOW unsupported: %s" % str(e)[:200]
        return {"ok": False, "reason": r}, {"ok": False, "task_status": None, "reason": r}


def probe_switch(c):
    wf = _wf("convo_platform_probe_switch", [
        {"name": "sw", "taskReferenceName": "sw_ref", "type": "SWITCH", "evaluatorType": "value-param",
         "expression": "v", "inputParameters": {"v": "taken"},
         "decisionCases": {"skipped": [_jq("skipped_ref", "{x: 1}")]}, "defaultCase": [_jq("taken_ref", "{x: 2}")]},
        _jq("after_ref", "{x: .x}", x="${skipped_ref.output.result.x}")], {"x": "${after_ref.output.result.x}"})
    try:
        run = _run(c, wf, {})
    except ConductorError as e:
        return {"ok": False, "value": None, "reason": str(e)[:200]}
    return {"ok": run.get("status") == "COMPLETED", "value": (run.get("output") or {}).get("x")}


def run_checks(start_ollama=True):
    c = Conductor()
    try:
        c._req("GET", "/metadata/workflow", params={"short": "true"}, timeout=5)
    except ConductorError as e:
        print("Conductor not reachable at %s: %s" % (c.base, e), file=sys.stderr)
        return 1
    model = config.get("CONVO_LLM_MODEL")
    up = ollama.ensure_running(wait=15) if start_ollama else ollama.tags() is not None
    have = ollama.tags() or []
    res = {"conductor": {"ok": True, "flavor": c.flavor, "url": c.base},
           "ollama": {"ok": bool(up and (model in have)), "up": bool(up), "model": model}}
    res["llm_native"] = probe_llm(c)
    res["get_workflow"], res["get_workflow_missing"] = probe_get_workflow(c)
    res["switch_not_taken"] = probe_switch(c)
    mode = "native" if res["llm_native"]["ok"] else "worker"
    os.makedirs(RUN_DIR, exist_ok=True)
    json.dump(res, open(os.path.join(RUN_DIR, "checks.json"), "w"), indent=2)
    open(os.path.join(RUN_DIR, "llm_mode"), "w").write(mode + "\n")
    print("%-22s %-5s %s" % ("check", "ok", "detail"))
    for k, v in res.items():
        detail = {kk: vv for kk, vv in v.items() if kk != "ok"}
        print("%-22s %-5s %s" % (k, "yes" if v.get("ok") else "NO", json.dumps(detail)[:110]))
    print("LLM mode: %s" % mode)
    return 0


if __name__ == "__main__":
    sys.exit(run_checks())

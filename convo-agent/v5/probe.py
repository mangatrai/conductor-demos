"""Verify first: what does this Conductor server support for agents?

python -m v5.probe          -> prints {"aiEnabled", "agentTask", "sdkSessionMemory", "notes", "agentMode"}
python -m v5.probe --write  -> also registers v5, swapping in the SIMPLE fallback when AGENT is unsupported
"""
import copy
import json
import os
import sys
import time

from common import RUN_DIR, APP_DIR, llm_mode, register
from common.conductor import Conductor, ConductorError

CACHE = os.path.join(RUN_DIR, "v5_probe.json")
TURN_FILE = os.path.join(APP_DIR, "v5", "conductor", "workflows", "convo_v5_agent_turn.json")


def _ai_enabled(c, notes):
    """The Agents API answers (an empty start is rejected with 400, not 404)."""
    try:
        c._req("POST", "/agent/start", json={})
        return True
    except ConductorError as e:
        ok = e.status not in (0, 404, 405)
        notes.append("agent API: HTTP %s %s" % (e.status, "(present)" if ok else "(missing)"))
        return ok


def _agent_task(c, notes):
    """Run a one-task workflow with an AGENT task; it works only if the server runs it to COMPLETED."""
    wf = {"name": "convo_v5_probe", "version": 1, "schemaVersion": 2, "ownerEmail": "convo-agent@example.com",
          "tasks": [{"name": "agent", "taskReferenceName": "agent_ref", "type": "AGENT",
                     "inputParameters": {"agentType": "conductor", "name": "wealth_advisor", "prompt": "ping"}}]}
    try:
        wid = c._req("POST", "/workflow", json={"name": "convo_v5_probe", "version": 1, "workflowDef": wf, "input": {}})
    except ConductorError as e:
        notes.append("AGENT task rejected: %s" % str(e)[:160])
        return False
    deadline, w = time.time() + 15, {}
    while time.time() < deadline:
        w = c.get_workflow(wid, include_tasks=True)
        if w.get("status") != "RUNNING":
            break
        time.sleep(0.5)
    if w.get("status") == "COMPLETED":
        return True
    task = (w.get("tasks") or [{}])[0]
    notes.append("AGENT task did not run: %s %s" % (task.get("status") or w.get("status"),
                                                     task.get("reasonForIncompletion") or w.get("reasonForIncompletion") or ""))
    c.terminate(wid, "v5 probe")
    return False


def probe(c=None):
    c = c or Conductor()
    notes = []
    report = {"aiEnabled": _ai_enabled(c, notes), "agentTask": _agent_task(c, notes),
              # SDK session memory needs server-side agent runs; not verified here, so v5 never relies on it
              "sdkSessionMemory": False, "flavor": c.flavor}
    notes.append("sdkSessionMemory not relied on: memory is loaded explicitly from the previous execution id")
    report["agentMode"] = "server" if report["agentTask"] else "local"
    report["notes"] = notes
    os.makedirs(RUN_DIR, exist_ok=True)
    with open(CACHE, "w") as f:
        json.dump(report, f, indent=2)
    return report


def local_variant(wf):
    """The same workflow with the one AGENT task swapped for SIMPLE convo_v5_agent_run (same inputs)."""
    wf = copy.deepcopy(wf)
    for t in wf["tasks"]:
        if t.get("type") == "AGENT":
            t.update(type="SIMPLE", name="convo_v5_agent_run")
    return wf


def write(c, report):
    """Register v5 (task defs + workflows), then the local variant if the server cannot run AGENT."""
    register.register_version("v5", c)
    if not report["agentTask"]:
        wf = local_variant(json.load(open(TURN_FILE)))
        c.register_workflow(register.prepare(wf, llm_mode.effective_mode(), None, llm_mode.get_workflow_ok()))


def ensure(c=None):
    """Front doors call this: register the right variant, probing once (result cached in .run/)."""
    c = c or Conductor()
    try:
        report = json.load(open(CACHE))
    except (OSError, ValueError):
        report = probe(c)
    write(c, report)
    return report


def main(argv):
    c = Conductor()
    try:
        report = probe(c)
        if "--write" in argv:
            write(c, report)
    except ConductorError as e:
        print(json.dumps({"error": str(e)}))
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

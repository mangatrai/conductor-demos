"""One chat turn.

run_turn()  - what front doors call: starts workflow convo_v5_agent_turn (memory + agent + save)
              and returns its S4-shaped output. Every turn is a Conductor execution.
run_agent() - the local agent run (agentMode "local"): the SDK Agent's instructions and tools,
              driven against Ollama. The v5 worker runs it for SIMPLE task convo_v5_agent_run
              when the server cannot run the AGENT task itself.
"""
import json

import requests
from conductor.ai.agents.tool import get_tool_def

from common import config
from common.conductor import Conductor
from v5 import memory
from v5.agent import build_agent
from v5.tools import clients

WORKFLOW = "convo_v5_agent_turn"


class TurnError(RuntimeError):
    pass


def _ollama(model, messages, tools):
    body = {"model": model, "messages": messages, "tools": tools, "stream": False,
            "options": {"temperature": 0.2, "num_predict": 512}}
    r = requests.post(config.get("OLLAMA_URL").rstrip("/") + "/api/chat", json=body, timeout=180)
    r.raise_for_status()
    return r.json().get("message") or {}


def run_agent(message, history=None):
    """Run the Agent locally: system prompt + prior turns + message, with tool calls. Raises on failure."""
    agent = build_agent()
    model = agent.model.split("/", 1)[1] if "/" in agent.model else agent.model
    defs = {d.name: d for d in (get_tool_def(t) for t in agent.tools)}
    tools = [{"type": "function", "function": {"name": d.name, "description": d.description,
                                               "parameters": d.input_schema}} for d in defs.values()]
    msgs = [{"role": "system", "content": agent.instructions}]
    msgs += [{"role": h.get("role", "user"), "content": h.get("message", "")} for h in history or []]
    msgs.append({"role": "user", "content": message})
    calls = []
    # small local models over-use tools: offer them only when the message is about a portfolio or a client
    named = [c["name"] for c in clients() if c["name"].lower() in message.lower()]
    if not named and not any(w in message.lower() for w in ("portfolio", "holding", "client named")):
        tools = []

    def call_tool(name, args):
        try:
            result = defs[name].func(**args)
        except Exception as e:  # unknown tool / bad arguments: tell the model, keep going
            result = {"error": "%s: %s" % (type(e).__name__, e)}
        calls.append({"name": name, "arguments": args})
        msgs.append({"role": "tool", "content": json.dumps(result)})

    for _ in range(agent.max_turns):
        out = _ollama(model, msgs, tools)
        if not out.get("tool_calls"):
            if calls or not named:
                return {"reply": (out.get("content") or "").strip(), "toolCalls": calls, "agentMode": "local"}
            # grounding: a client was named but the model skipped the tool -> look it up and ask again
            msgs.append({"role": "assistant", "content": "",
                         "tool_calls": [{"function": {"name": "get_portfolio", "arguments": {"client_name": named[0]}}}]})
            call_tool("get_portfolio", {"client_name": named[0]})
            continue
        msgs.append(out)
        for tc in out["tool_calls"]:
            fn = tc.get("function") or {}
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                args = json.loads(args or "{}")
            call_tool(fn.get("name"), args)
    raise TurnError("agent did not finish within %d steps" % agent.max_turns)


def run_turn(session_id, message, prev_execution_id="", wait_seconds=240):
    """Start convo_v5_agent_turn (correlationId = session) and return its output plus uiUrl."""
    from v5 import probe, worker  # setup helpers: register the right workflow variant, poll the agent task
    conductor = Conductor()
    probe.ensure(conductor)
    worker.start_polling()
    if not prev_execution_id:
        prev_execution_id = memory.find_prev(conductor, session_id)
    wf = conductor.run_sync(WORKFLOW, {"sessionId": session_id, "prevExecutionId": prev_execution_id or "",
                                       "message": message}, correlation_id=session_id, wait_seconds=wait_seconds)
    wid = wf.get("workflowId")
    if wf.get("status") != "COMPLETED":
        raise TurnError("execution %s ended %s: %s" % (wid, wf.get("status"), wf.get("reasonForIncompletion") or ""))
    out = dict(wf.get("output") or {})
    out.setdefault("executionId", wid)
    out["uiUrl"] = conductor.ui_url(wid)
    return out

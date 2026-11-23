"""v4: the v3-style chat turn and portfolio lookup, exposed as MCP tools.

    python -m v4.mcp_server                       # Streamable HTTP at http://localhost:8740/mcp (+ GET /healthz)
    python -m v4.mcp_server --transport stdio     # for Claude Desktop

Every tool call starts a Conductor workflow and returns its output plus a link to the execution,
so the person in Claude Desktop can click through to the Conductor UI.

Tools
  ask_wealth_advisor(message, sessionId?, prevExecutionId?, llmProvider?, model?) -> convo_v4_chat_turn
  get_portfolio(clientName)                                                     -> convo_v4_get_portfolio
"""
import argparse
import json
import sys
import uuid

import anyio

from common.conductor import TERMINAL, Conductor, ConductorError

try:  # mcp 2.x
    from mcp.server.mcpserver import Context, MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import Context, FastMCP as _Server
try:
    from mcp_types import CallToolResult
except ImportError:
    from mcp.types import CallToolResult

NAME = "convo-v4-wealth-advisor"
WAIT_SECONDS = 90  # router LLM + optional lookup + answer LLM on a small local model

server = _Server(NAME, instructions="A wealth-advisor demo assistant. Every tool call runs a Conductor workflow; "
                                    "the result ends with a link to that execution.")

# Session pointers per MCP session: {session_key: {"sessionId": str, "executionId": str}}.
# In memory on purpose: a server restart is a new chat. Callers that pass the ids are stateless.
POINTERS = {}


def result(text, data=None, error=False):
    """Build a CallToolResult that works on mcp 1.x and 2.x (validate with the wire names)."""
    body = {"content": [{"type": "text", "text": text}], "isError": error}
    if data is not None:
        body["structuredContent"] = data
    return CallToolResult.model_validate(body)


def run_workflow(name, inputs, correlation_id=None):
    """Run a workflow and wait. Returns (workflow, conductor). Raises ConductorError when unreachable."""
    try:
        conductor = Conductor()  # built per call, so a down Conductor never stops the server from starting
    except Exception as e:
        raise ConductorError(0, "/", "cannot build client: %s" % e)
    return conductor.run_sync(name, inputs, correlation_id=correlation_id, wait_seconds=WAIT_SECONDS), conductor


def outcome(wf, conductor, summary):
    """Map a finished (or still running) execution to a tool result."""
    wid = wf.get("workflowId", "")
    url = conductor.ui_url(wid)
    status = wf.get("status")
    data = dict(wf.get("output") or {})
    data.update(executionId=wid, uiUrl=url, status=status)
    if status == "COMPLETED":
        return result("%s\n\nExecution: %s" % (summary(data), url), data)
    if status in TERMINAL:
        reason = wf.get("reasonForIncompletion") or status
        return result("Workflow %s %s: %s\n\nExecution: %s" % (wf.get("workflowName", ""), status, reason, url), data, True)
    return result("Workflow still %s after %ss (executionId %s); open it in Conductor.\n\nExecution: %s"
                  % (status, WAIT_SECONDS, wid, url), data, True)


def unreachable(e):
    return result("Conductor unreachable: %s. Start it (./convo.sh start v4) and try again." % e,
                  {"status": "CONDUCTOR_UNREACHABLE", "error": str(e)}, True)


def session_key(ctx):
    """One key per MCP session: the Mcp-Session-Id header over HTTP, the process-wide session on stdio."""
    try:
        request = ctx.request_context.request
        sid = request.headers.get("mcp-session-id") if request is not None else None
        if sid:
            return "http-" + sid
    except Exception:
        pass
    return "stdio"


def chat_turn(key, message, sessionId="", prevExecutionId="", llmProvider="", model=""):
    """Pointer algorithm (design/v4.md): args win, else stored pointer, else a new session."""
    ptr = POINTERS.get(key) or {}
    sid = sessionId or ptr.get("sessionId") or str(uuid.uuid4())
    prev = prevExecutionId or (ptr.get("executionId", "") if ptr.get("sessionId") == sid else "")
    inputs = {"sessionId": sid, "prevExecutionId": prev, "message": message}
    if llmProvider:
        inputs["llmProvider"] = llmProvider
    if model:
        inputs["model"] = model
    try:
        wf, conductor = run_workflow("convo_v4_chat_turn", inputs, correlation_id=sid)
    except ConductorError as e:
        return unreachable(e)
    if wf.get("status") == "COMPLETED":  # never advance the pointer on failure (PRD v1 rule)
        POINTERS[key] = {"sessionId": sid, "executionId": wf.get("workflowId", "")}
    res = outcome(wf, conductor, lambda d: d.get("reply", ""))
    if res_data(res) is not None:
        res_data(res).setdefault("sessionId", sid)
    return res


def res_data(res):
    return getattr(res, "structured_content", getattr(res, "structuredContent", None))


def portfolio_text(d):
    p = d.get("portfolio") or {}
    if d.get("found") and p:
        lines = ["%s (%s risk, advisor %s): total %s %s, YTD %s%%" % (
            p["client"]["name"], p["client"]["riskProfile"], p["client"]["advisor"],
            "{:,}".format(p["totalValue"]), p.get("currency", ""), p.get("ytdReturnPct"))]
        lines += ["- %s %s (%s): %s, %s%%" % (h["symbol"], h["name"], h["assetClass"], "{:,}".format(h["value"]), h["weightPct"])
                  for h in p.get("holdings", [])]
        lines.append("holdings: " + json.dumps(p.get("holdings", [])))
        return "\n".join(lines)
    if d.get("error"):
        return "Portfolio data is temporarily unavailable (%s)." % d["error"]
    known = ", ".join(d.get("known") or [])
    return "No client named %r. Known clients: %s" % (d.get("clientName"), known or "none")


@server.tool(description="Ask the wealth-advisor assistant a question. The conversation is remembered per MCP "
                         "session; pass sessionId/prevExecutionId to continue a specific chat. It can look up "
                         "client portfolios (e.g. 'What is in Jane Doe's portfolio?').")
async def ask_wealth_advisor(message: str, ctx: Context, sessionId: str = "", prevExecutionId: str = "",
                             llmProvider: str = "", model: str = ""):
    key = session_key(ctx)
    print("ask_wealth_advisor session key %s" % key, file=sys.stderr, flush=True)
    return await anyio.to_thread.run_sync(lambda: chat_turn(key, message, sessionId, prevExecutionId, llmProvider, model))


@server.tool(description="Look up a client's portfolio (holdings, total value, YTD return) by full name, "
                         "e.g. 'Jane Doe'. Runs the convo_v4_get_portfolio workflow.")
async def get_portfolio(clientName: str):
    def run():
        try:
            wf, conductor = run_workflow("convo_v4_get_portfolio", {"clientName": clientName})
        except ConductorError as e:
            return unreachable(e)
        return outcome(wf, conductor, portfolio_text)
    return await anyio.to_thread.run_sync(run)


@server.custom_route("/healthz", methods=["GET"])
async def healthz(request):
    from starlette.responses import JSONResponse
    return JSONResponse({"status": "ok", "server": NAME, "tools": ["ask_wealth_advisor", "get_portfolio"]})


def main():
    ap = argparse.ArgumentParser(description="v4 MCP server over Conductor workflows")
    ap.add_argument("--transport", choices=["http", "stdio"], default="http")
    ap.add_argument("--port", type=int, default=8740)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    if args.transport == "stdio":
        server.run("stdio")
        return
    print("v4 MCP server on http://%s:%d/mcp" % (args.host, args.port), file=sys.stderr, flush=True)
    if _Server.__name__ == "MCPServer":  # mcp 2.x takes host/port as run() kwargs
        server.run("streamable-http", host=args.host, port=args.port)
    else:  # mcp 1.x keeps them in settings
        server.settings.host, server.settings.port = args.host, args.port
        server.run("streamable-http")


if __name__ == "__main__":
    main()

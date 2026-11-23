# v4: the same workflows as MCP tools

v4 does not change the bot. It takes the v3 workflows (chat turn with router, Switch, Sub Workflow and HTTP
lookup), snapshots them as `convo_v4_*`, and exposes them as **MCP tools** so Claude Desktop, MCP Inspector or
any MCP client can use the agent. Every tool call is a Conductor execution you can open in the UI.

```
./convo.sh start v4      # registers workflows, starts MCP server :8740 and mock portfolio API :8741
./convo.sh smoke v4      # MCP client: list tools, get_portfolio, two chat turns that remember
./convo.sh stop v4
```

| Piece | What it shows |
|---|---|
| `mcp_server.py` | ~150 lines: MCP tools are thin wrappers over "start workflow, wait, return output + link" |
| `conductor/workflows/convo_v4_chat_turn.json` | `GET_WORKFLOW` memory by id, LLM router (JSON output), `SWITCH`, `SUB_WORKFLOW`, `LLM_CHAT_COMPLETE`, JQ |
| `conductor/workflows/convo_v4_get_portfolio.json` | `HTTP` task to the mock API, JQ shaping; same workflow is the sub workflow and a tool |
| `conductor/workflows/convo_v4_chat_history.json` | resume helper (read history of a turn by id) |
| `claude_desktop/` | ready-to-paste Claude Desktop configs (stdio and `mcp-remote`) |
| `gateway/` | the Orkes MCP Gateway version: no server code at all |

## Tools

- `ask_wealth_advisor(message, sessionId?, prevExecutionId?, llmProvider?, model?)` runs `convo_v4_chat_turn`
  with `correlationId = sessionId`. Without ids the server keeps one chat per MCP session (in memory); the
  pointer only moves on a COMPLETED turn. Result: reply text + `Execution: <url>`, structured content =
  workflow output (`reply`, `history`, `sessionId`, `restored`, `lookup`) + `executionId`, `uiUrl`, `status`.
- `get_portfolio(clientName)` runs `convo_v4_get_portfolio`; unknown names return `found: false` and the
  known names (not an error).

Errors are tool errors (`isError`), never crashes: Conductor down → "Conductor unreachable"; workflow
FAILED/TERMINATED → reason + link; still running after 90 s → executionId + link.

Run by hand: `python -m v4.mcp_server --transport http --port 8740` (endpoint `/mcp`, health `/healthz`) or
`--transport stdio`. Works with the `mcp` package 1.x (FastMCP) and 2.x (MCPServer).

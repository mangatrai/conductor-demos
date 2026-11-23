# Claude Desktop: use the v4 wealth advisor

Two ways to plug the v4 MCP server into Claude Desktop. Both run the same Conductor workflows
(`convo_v4_chat_turn`, `convo_v4_get_portfolio`); every tool call shows up as an execution in the
Conductor UI and the tool result ends with `Execution: <link>`.

Open Claude Desktop → Settings → Developer → Edit Config (`~/Library/Application Support/Claude/claude_desktop_config.json`
on macOS), merge one of the `mcpServers` blocks below in, and restart Claude Desktop.

## Option A: stdio (Claude Desktop starts the server itself)

`claude_desktop_config.stdio.json`. Replace:

- `command`: the Python of your venv (`which python` after activating it);
- `PYTHONPATH`: the absolute path of this repo's `convo-agent/` folder (so `-m v4.mcp_server` is found).

Conductor (and Ollama, for the chat tool) must be running, and the workflows registered:
`./convo.sh start v4` does both, and also starts the mock portfolio API on 8741 that `get_portfolio` calls.

## Option B: remote HTTP via `mcp-remote`

`claude_desktop_config.remote.json`. Start the stack with `./convo.sh start v4` (the MCP server listens on
`http://localhost:8740/mcp`), then Claude Desktop reaches it through `npx mcp-remote` (needs Node.js).
The same URL works for any MCP client that speaks Streamable HTTP (MCP Inspector:
`npx @modelcontextprotocol/inspector`, transport "Streamable HTTP", URL above).

For the Orkes-hosted variant (Orkes MCP Gateway instead of this local server) see `../gateway/SETUP.md`.

## Try it

- "Use the wealth advisor: what's in Jane Doe's portfolio?"  → `get_portfolio` or `ask_wealth_advisor`
- "Ask the wealth advisor: my name is Sam and my goal is retiring at 55." then "What did I say my goal was?"
  → the second call continues the same chat (same `sessionId`, `restored: true`).

If Conductor is down the tools return an error saying "Conductor unreachable" instead of crashing.

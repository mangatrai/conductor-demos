# v4 on Orkes: the MCP Gateway instead of the local server

On Orkes Conductor you do not need `v4/mcp_server.py` at all: the **MCP Gateway** turns workflows into MCP
tools. `orkes_mcp_service.json` describes the service this demo needs (one service, two tools).

1. Register the workflows on Orkes: put `CONDUCTOR_SERVER_URL=https://<cluster>.orkesconductor.io/api`,
   `CONDUCTOR_AUTH_KEY` and `CONDUCTOR_AUTH_SECRET` in `convo-agent/.env` and run `./convo.sh start v4`
   (it registers `convo_v4_chat_turn`, `convo_v4_get_portfolio`, `convo_v4_chat_history`).
2. The mock portfolio API must be reachable from Orkes, so `localhost:8741` will not do. Host
   `v4/data/portfolios.json` somewhere public (a raw GitHub URL works for the demo) and point the HTTP task
   `http_ref` in `convo_v4_get_portfolio` at it, or expose the mock with a tunnel.
3. In the Orkes UI open **MCP Gateway → Create service**, name it `convo-v4-wealth-advisor`, auth "API key",
   and add the two tools from `orkes_mcp_service.json` (tool name → workflow, input schema), or paste the JSON
   if your cluster offers the JSON editor.
4. Copy the service's **MCP Tool Remote Endpoint** URL and create an application API key with execute
   permission on both workflows.
5. In Claude Desktop use the remote config with that URL and key:

```json
{
  "mcpServers": {
    "convo-v4-wealth-advisor-orkes": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "<MCP Tool Remote Endpoint>", "--header", "X-Authorization:${ORKES_KEY}"],
      "env": {"ORKES_KEY": "<your key>"}
    }
  }
}
```

Difference from the local server: the gateway is stateless, so the caller (Claude) passes `sessionId` and
`prevExecutionId` itself; the local server can also remember them per MCP session.

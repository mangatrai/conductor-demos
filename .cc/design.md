# Contract the checks use

Seams: see `design/architecture.md` §3 (S1–S6) and its "Review decisions (binding)" section.
All commands run from `convo-agent/` with `/Users/mrai/.uv/venvs/conductor/bin/python`.

## Environment
- Conductor OSS `CONDUCTOR_SERVER_URL=http://localhost:8080/api` (UI links on :5000/:8080 per S1).
- Ollama `OLLAMA_URL=http://localhost:11434`, model `CONVO_LLM_MODEL=qwen2.5:3b`, `CONVO_LLM_PROVIDER`.
- Config order: real env > `convo-agent/.env` > repo `.env`.
- S2 placeholders: `{{LLM_PROVIDER}}`, `{{LLM_MODEL}}`, `{{MOCK_BASE_URL}}`, `{{CONDUCTOR_API}}`.

## Launcher / platform
- `./convo.sh setup|start|stop|status|smoke|list|checks [v1..v5|all]`; unknown version → exit 2.
- `.run/` pids+logs, `.run/checks.json` (keys llm_native, get_workflow, get_workflow_missing,
  switch_not_taken), `.run/llm_mode` = `native|worker`.
- Hub `python -m hub.server --port 8700`: `GET /api/versions`, `GET /api/platform`, page has "Version tour".

## Ports
hub 8700 · v2 web 8720 · v3 web 8730, mock 8731 · v4 MCP 8740 (`/mcp`, `/healthz`), mock 8741 ·
v5 web 8750, worker 8751.

## Per version
- v1: workflow `convo_v1_chat_turn`; `python -m v1.chat [--resume]`; `python -m v1.smoke`.
- v2: `python -m v2.server --version vN --port P [--title] [--static-dir] [--client mod:Class]`;
  `/api/chat` (400/502/504), `/api/session`, `/api/config`, `/healthz`; `python -m v2.smoke`;
  `python -m v2.gateway.setup_gateway --dry-run`.
- v3: `convo_v3_chat_turn` (+`lookup`), `convo_v3_get_portfolio`, `python -m v3.mock_api --port 8731 [--fail]`;
  Jane Doe totalValue 1250000, ytdReturnPct 6.4; `python -m v3.smoke`.
- v4: `python -m v4.mcp_server --transport http|stdio --port 8740`, tools `ask_wealth_advisor(message)`,
  `get_portfolio(clientName)`; `python -m v4.smoke`.
- v5: `python -m v5.chat --session S [--prev ID] "msg"` (prints JSON incl. reply, restored,
  memorySource, memoryNote, agentMode, executionId, toolCalls); `python -m v5.probe` (JSON with
  aiEnabled, agentTask, sdkSessionMemory booleans); workflow `convo_v5_agent_turn` (output reply,
  history, executionId, agentMode `server|local`); web `/api/chat` on 8750; `python -m v5.smoke`
  prints memorySource and agentMode.
- Chat-turn input (S4): sessionId, prevExecutionId, message, llmProvider, model, systemPrompt;
  correlationId = sessionId; history ≤ 20 starting with user.

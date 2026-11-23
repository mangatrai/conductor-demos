# convo-agent: a conversational agent built on Conductor, one version at a time

A wealth-advisor chat bot, built in five steps. Each step shows more of what Conductor / Orkes Conductor
can do. Every version stays in the tree as `vN/` and runs **on its own or alongside the others**.
Each version has its own workflow names and ports.

| Version | What it adds | Conductor features it uses | Details |
|---|---|---|---|
| **v1** | Terminal chat with memory across executions | Switch, Get Workflow, JSON JQ Transform, LLM Chat Complete, Correlation ID search | `v1/chat.py` |
| **v2** | A web chat page behind a gateway; reload and resume | API Gateway (local stand-in, plus the Orkes service JSON), sync execution, Get Workflow resume | [v2/README.md](v2/README.md) |
| **v3** | The bot does real work: portfolio lookup | LLM JSON output as a router, Switch, Sub Workflow, HTTP task (optional, with retry) | [v3/README.md](v3/README.md) |
| **v4** | The same workflows as MCP tools (Claude Desktop, MCP Inspector) | MCP server over workflows, Orkes MCP Gateway, correlationId sessions | [v4/README.md](v4/README.md) |
| **v5** | The same bot in ~30 lines of Python | Agents SDK (`Agent`, `@tool`), AGENT task, SIMPLE worker fallback | [v5/README.md](v5/README.md) |

Every chat turn is one Conductor execution, so you can open any answer in the Conductor UI and see
how it was produced.

## Quick start

You need Python 3.13 and [uv](https://docs.astral.sh/uv/), a Conductor server (local Conductor OSS at
`http://localhost:8080/api` by default, or Orkes), and an LLM (below).

Create a virtual environment wherever you like and activate it; `convo.sh` uses the `python3` of the
active environment (or `CONVO_PYTHON` when you set it):

```bash
uv venv --python 3.13 .venv     # any location works
source .venv/bin/activate       # Windows: .venv\Scripts\activate
```

Then:

```bash
cd convo-agent
./convo.sh setup            # install requirements into the active venv, create .env, pull qwen2.5:3b
./convo.sh start v2 v3      # register workflows, start the processes and the hub
./convo.sh status           # version / process / pid / port / healthy
open http://localhost:8700/ # the hub
./convo.sh stop all         # stop every version, the LLM worker, the hub (and Ollama if we started it)
```

Other commands: `./convo.sh list` (versions and their features), `./convo.sh smoke v3` (end-to-end check),
`./convo.sh checks` (Step-0: what this Conductor supports, written to `.run/checks.json`).
Settings come from `convo-agent/.env` (copy `.env.example`): `CONDUCTOR_SERVER_URL`, `CONDUCTOR_AUTH_KEY`/`SECRET`
for Orkes, `CONVO_LLM_MODEL`, `CONVO_LLM_MODE` (`auto`|`native`|`worker`), `OLLAMA_URL`.

### The LLM: Ollama here, any provider you like

This exercise uses [Ollama](https://ollama.com) with `qwen2.5:3b`, so everything runs locally for free.
`./convo.sh setup` and `start` launch `ollama serve` if Ollama is installed but not running, and pull the model.

You are free to use any LLM. Conductor OSS 3.34 has built-in providers for 12 LLM services: OpenAI,
Azure OpenAI, Anthropic, Google Gemini, AWS Bedrock, Mistral, Cohere, Grok, Perplexity, Hugging Face,
Ollama and LiteLLM (which fronts many more). Choose whatever fits your needs: configure that provider
on your Conductor server, then set `CONVO_LLM_PROVIDER` and `CONVO_LLM_MODEL` in `.env` and
`CONVO_LLM_MODE=native`, so the workflows' LLM tasks call it through Conductor. The `worker` mode
(the fallback when the server cannot run LLM tasks itself) talks to Ollama only.

## The hub: http://localhost:8700/

`./convo.sh start …` also starts the hub (`python -m hub.server --port 8700`). It shows:
- a **platform strip**: Conductor flavor, LLM mode (native `LLM_CHAT_COMPLETE` or the `convo_llm_chat` worker),
  model, whether Ollama is up, and any failed Step-0 check in red;
- a **card per version**: summary, feature chips, a live status dot, links, and copy buttons for
  `./convo.sh start vN` / `./convo.sh stop vN`. The hub only shows status. It never starts or stops anything;
- the **Version tour**: a table of features by version, where **new** marks the version that introduces each one.

APIs: `GET /api/versions`, `GET /api/platform`. The page refreshes every 5 s.

## Ports

| Process | Port |
|---|---|
| hub | 8700 |
| v1 | none (terminal: `python -m v1.chat`) |
| v2 web | 8720 |
| v3 web / mock portfolio API | 8730 / 8731 |
| v4 MCP server (`/mcp`) / mock portfolio API | 8740 / 8741 |
| v5 web / worker | 8750 / 8751 |
| Conductor API / UI (OSS defaults) | 8080 / 5000 |
| Ollama | 11434 |

## Demo script per version

**v1: memory without a database**
1. `./convo.sh start v1`, then `python -m v1.chat`.
2. Say "My client is 55 and wants to retire at 62", then ask "How many years does she have left?". The bot remembers.
3. Type `/links`: open the execution. Switch → Get Workflow (previous turn) → JQ → LLM → JQ.
4. `/quit`, then `python -m v1.chat --resume`: the conversation continues from the last execution.

**v2: a web page on a gateway**
1. `./convo.sh start v2`, open http://localhost:8720/.
2. Ask a starter question. Under the reply, "what Conductor did" lists every task with its timing.
3. Click **execution ↗** and **session ↗** (correlation-id search of every turn).
4. Reload the page and choose **Continue?**: the history comes back from Conductor through Get Workflow.

**v3: the bot does real work**
1. `./convo.sh start v3`, open http://localhost:8730/.
2. "What's in Jane Doe's portfolio?" → real numbers from the HTTP task in a Sub Workflow.
3. "What is a Roth IRA?" → no lookup (the Switch takes the default branch).
4. Restart the mock with `python -m v3.mock_api --port 8731 --fail`: the turn still completes and the bot says the data is unavailable.

**v4: the same workflows as MCP tools**
1. `./convo.sh start v4`, then `./convo.sh smoke v4` (lists the tools, calls `get_portfolio`, runs two chat turns).
2. Paste `v4/claude_desktop/claude_desktop_config.remote.json` into Claude Desktop, or point MCP Inspector at http://localhost:8740/mcp.
3. Ask Claude about Jane Doe's portfolio. Each tool call is a Conductor execution, linked in the answer.
4. For Orkes: `v4/gateway/SETUP.md` exposes the same workflows through the Orkes MCP Gateway, with no server code.

**v5: the same bot as a Conductor Agent**
1. `./convo.sh start v5`, open http://localhost:8750/.
2. Read `v5/agent.py`: `Agent(name="wealth_advisor", tools=[get_portfolio])`.
3. `python -m v5.chat --session demo "What's in Jane Doe's portfolio?"` → the `@tool` is called.
4. `./convo.sh smoke v5` reports `agentMode` (native AGENT task or the reported SIMPLE worker fallback).

Run several at once (`./convo.sh start all`) and compare them side by side in the hub.

## Troubleshooting

- **Chat turns hang or fail with an LLM error**: Ollama must be running with the model pulled.
  `curl localhost:11434/api/tags` should list `qwen2.5:3b`. Start it with
  `ollama serve` and pull the model with `ollama pull qwen2.5:3b`.
  If `.run/llm_mode` says `worker`, the `convo_llm_chat` worker must be running. `./convo.sh start` starts it.
- **Conductor error / connection refused**: check `CONDUCTOR_SERVER_URL` (default `http://localhost:8080/api`).
  For Orkes, set `CONDUCTOR_AUTH_KEY` and `CONDUCTOR_AUTH_SECRET`. Delete `.run/llm_mode` and run
  `./convo.sh checks` again after you switch servers.
- **Port already in use**: `./convo.sh status` shows which process is healthy. Run `./convo.sh stop vN` (or `stop all`) first,
  or find the owner with `lsof -i :8720`. Starting a version that is already running and healthy is a no-op.
- **Logs**: `.run/<version>/<process>.log`, `.run/hub.log`, `.run/llm_worker.log`.

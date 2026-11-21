# convo-agent — architecture (the split and the seams)

Source of truth for *what* to build: `design/PRD.md` (copy of `convo-agent/PRD.md`, Rev 2).
This file fixes only *who owns what* and the interfaces the parts share. Everything else is
each part's own design.

## 1. What the system is

A wealth-advisor chat assistant built on Conductor, delivered as **versions v1..v5**, each a
self-contained, runnable demo of more Conductor features (PRD roadmap). Any version can be run
alone, or several at once, from one launcher. All work lives under `convo-agent/` in the repo
root. Nothing outside `convo-agent/` is created or edited.

Runtime on this machine (verified): **Conductor OSS at `http://localhost:8080/api`**
(`CONDUCTOR_FLAVOR=oss` in the repo `.env`), **Ollama** at `http://localhost:11434`
(started/stopped with `/Users/mrai/sandbox/castles/help-scripts/start_ollama.sh` /
`stop_ollama.sh`), no Docker. Orkes (cloud) stays supported through the same env vars, but OSS +
Ollama is the path that must work end to end. Orkes-only features (API Gateway, MCP Gateway)
get a local stand-in on OSS, exactly as the PRD's "fallback" allows; the Orkes configuration is
documented/scripted alongside.

Request flow (one chat turn, any version with a web front door):

```
browser ──HTTP──> vN front door (local server, port 87N0)
                     │  run workflow sync, correlationId = sessionId
                     ▼
              Conductor: convo_vN_chat_turn
                 Get Workflow(prevExecutionId) → JQ build → [v3+: router LLM → Switch → Sub Workflow
                 convo_vN_get_portfolio → HTTP mock API] → LLM chat (native LLM task or
                 convo_llm_chat worker → Ollama) → JQ save
                     │  output {reply, history, executionId, ...}
                     ▼
browser stores executionId (only on success) and shows reply + links to the execution in the UI
```

v4 swaps the browser for an MCP client (Claude Desktop); v5 swaps the workflow for a Conductor Agent.

## 2. Shared decisions

- **Language/runtime:** Python 3.13, shared venv `/Users/mrai/.uv/venvs/conductor`
  (`conductor-python` 2.0.0 installed). No Node, no npm, no bundler: web pages are static
  HTML/JS/CSS served by the Python servers.
- **Layout** (all under `convo-agent/`):
  ```
  convo-agent/
    PRD.md  README.md  requirements.txt  pytest.ini  .env.example  .gitignore
    convo.sh                 # the one launcher (owned by platform)
    common/                  # shared Python package (owned by platform)
    hub/                     # landing page listing all versions (owned by platform)
    v1/ v2/ v3/ v4/ v5/      # one folder per version, each owned by its part
  ```
  Python is always run with `convo-agent/` as the working directory and on `PYTHONPATH`, so
  `import common`, `import v2.server` work. Version folders are Python packages.
- **Versions are snapshots, not layers.** Each `vN/` holds its *complete* set of workflow and
  task definitions, so editing v3 can never break v1. A later version may start by copying the
  earlier one's JSON and evolving it (this is the "evolution" story the demo tells). The only
  code a version may import from another version is the v2 web front door (seam S5).
- **Names (so versions run side by side in one Conductor):** every workflow and task def a
  version registers is named `convo_v<N>_<name>` (e.g. `convo_v1_chat_turn`,
  `convo_v3_get_portfolio`). The one shared task def is `convo_llm_chat` (seam S3), owned by
  platform. Workflow def `version` is always `1`; re-registering overwrites.
- **Ports:** hub `8700`. Version N owns the block `87N0–87N9` (v1 8710…, v2 8720…, v3 8730…,
  v4 8740…, v5 8750…). Port `87N0` is the version's main front door if it has one.
- **Config:** env vars, loaded by `common.config` from `convo-agent/.env`, then the repo-root
  `.env`, never overriding real env vars. Keys: `CONDUCTOR_SERVER_URL`, `CONDUCTOR_AUTH_KEY`,
  `CONDUCTOR_AUTH_SECRET`, `CONDUCTOR_FLAVOR` (`oss`|`orkes`), `CONDUCTOR_UI_URL`,
  `CONVO_LLM_PROVIDER` (integration name passed as `llmProvider`), `CONVO_LLM_MODEL`,
  `CONVO_LLM_MODE` (`native`|`worker`|`auto`, default `auto`), `OLLAMA_URL`
  (default `http://localhost:11434`). Secrets never committed.
- **LLM:** default provider is local Ollama with a small model the platform part chooses and
  pulls (must handle JSON-intent output for v3). Workflows always carry `llmProvider` + `model`
  as workflow inputs with defaults (PRD: provider swap is an input, not an edit).
- **Tests:** pytest. Each part keeps its tests in its own folder (`common/tests`, `vN/tests`).
  Tests that need a live Conductor/Ollama are marked `@pytest.mark.live`; the rest run offline.
- **Spec:** OpenSpec. Each part writes its own capability under
  `openspec/specs/<part-id>/spec.md` (requirements + scenarios, each with an acceptance check).

## 3. Seams (fixed; design inside your part against these)

### S1. `common.conductor` — the Conductor client (platform provides, everyone uses)

```python
class ConductorError(RuntimeError):      # any non-2xx or network failure
    status: int                          # HTTP status, 0 for network error
    path: str
    body: str

class Conductor:
    def __init__(self) -> None           # reads common.config; handles Orkes JWT; OSS = no auth
    flavor: str                          # "oss" | "orkes"
    def register_task_defs(self, defs: list[dict]) -> None
    def register_workflow(self, wf: dict) -> None                       # create-or-overwrite
    def start_workflow(self, name: str, input: dict, correlation_id: str | None = None) -> str
    def run_sync(self, name: str, input: dict, correlation_id: str | None = None,
                 wait_seconds: int = 30) -> dict
        # returns the workflow run: {"workflowId","status","output","reasonForIncompletion",...}
        # status may still be RUNNING if the wait elapsed (caller decides; no exception)
    def get_workflow(self, workflow_id: str, include_tasks: bool = False) -> dict
        # raises ConductorError(status=404) if not found
    def search_by_correlation(self, correlation_id: str, workflow_name: str | None = None,
                              size: int = 50) -> list[dict]   # summaries, newest first
    def ui_url(self, workflow_id: str | None = None, correlation_id: str | None = None) -> str
```

### S2. Version registration — files each version provides, platform applies

Each `vN/` contains `conductor/workflows/*.json` (workflow defs) and optionally
`conductor/tasks/*.json` (a JSON list of task defs per file). Platform's registrar
(`common.register.register_version("v3") -> list[str]` of registered names) loads them and,
before sending:

1. replaces the literal placeholders `"{{LLM_PROVIDER}}"` and `"{{LLM_MODEL}}"` anywhere in
   the JSON with `CONVO_LLM_PROVIDER` / `CONVO_LLM_MODEL`; `"{{MOCK_BASE_URL}}"` with
   `http://localhost:<port>` given in the manifest's `mock_base_url_port` (S6), if any;
2. if the effective LLM mode is `worker`, rewrites every task with `"type": "LLM_CHAT_COMPLETE"`
   into `"type": "SIMPLE", "name": "convo_llm_chat"`, keeping `taskReferenceName` and
   `inputParameters` unchanged (so `${ref.output.result}` keeps working).

Authors therefore write native `LLM_CHAT_COMPLETE` tasks with `llmProvider`, `model`,
`messages: [{"role": "system"|"user"|"assistant", "message": str}]`, `temperature`,
`maxTokens`, optional `jsonOutput: true`, and read `${ref.output.result}`.

### S3. `convo_llm_chat` — fallback LLM worker (platform owns)

SIMPLE task, input exactly the native task's inputParameters above. Output:
`{"result": <str>}`, or when `jsonOutput` is true `{"result": <parsed JSON object>}`
(falls back to the raw string if it cannot parse). Calls Ollama `/api/chat` at `OLLAMA_URL`.
Failure → task FAILED with the error text; retry count 2. Run by
`python -m common.llm_worker`, started by the launcher whenever mode is `worker`.

### S4. Chat-turn contract (every version whose bot is a workflow: v1–v4)

Workflow `convo_vN_chat_turn`, started with `correlationId = sessionId`.

- **Input:** `sessionId` (str, required), `prevExecutionId` (str, `""` on turn 1),
  `message` (str), `llmProvider` (str, default `{{LLM_PROVIDER}}`), `model`
  (default `{{LLM_MODEL}}`), `systemPrompt` (str, default the PRD persona).
- **Output (always present):** `reply` (str), `history` (list of `{role, message}`, only
  user/assistant pairs, ≤ 20, starts with `user`), `executionId` (str), `sessionId` (str),
  `restored` (bool). **Optional extras** (any version may add keys, e.g. v3 `lookup`); front
  doors pass unknown keys through untouched.
- Invalid/foreign/missing `prevExecutionId` → fresh start with `restored=false` (PRD v1 rule).

Companion workflow `convo_vN_chat_history` (v2 onward, for resume):
input `{executionId, sessionId}` → output `{found: bool, history: [...], sessionId}`;
`found=false` when the execution is missing, not COMPLETED, or belongs to another session.

### S5. Web chat front door (v2 owns; v3 and others reuse by CLI)

Started as:
```
python -m v2.server --version vN --port 87N0 [--title "..."] [--static-dir vN/web]
```
It serves the chat page at `/` (from `--static-dir` if given, else v2's page) and proxies to
workflows `convo_<version>_chat_turn` / `convo_<version>_chat_history` (the stand-in for the
Orkes API Gateway). HTTP API (same routes as the PRD's gateway service, under `/api`):

| Route | Request | 200 response | Errors |
|---|---|---|---|
| `POST /api/chat` | `{sessionId, prevExecutionId, message, llmProvider?, model?}` | chat_turn output (S4) + `uiUrl` (execution link) + `sessionUrl` (correlation search link) | `400 {error}` bad body; `502 {error, executionId?}` workflow FAILED/TERMINATED; `504 {error, executionId}` still running after 30 s |
| `GET /api/session?sessionId=&executionId=` | — | chat_history output (S4) | `400`, `502` |
| `GET /api/config` | — | `{version, title, features: [str], flavor, conductorUiUrl, llmProvider, model}` | — |
| `GET /healthz` | — | `{ok: true}` | — |

The page keeps `sessionId` + last good `executionId` in `localStorage` keyed by version, so
two versions open in one browser never share a session.

### S6. Version manifest + launcher (each version provides, platform runs)

Each `vN/manifest.json`:
```json
{
  "version": "v3",
  "title": "Chat that does real work",
  "summary": "one sentence for the hub",
  "features": ["Sub Workflow", "HTTP task", "LLM JSON output", "Switch"],
  "processes": [
    {"name": "web",  "cmd": ["python", "-m", "v2.server", "--version", "v3", "--port", "8730"],
     "port": 8730, "health": "/healthz"},
    {"name": "mock", "cmd": ["python", "-m", "v3.mock_api", "--port", "8731"],
     "port": 8731, "health": "/healthz"}
  ],
  "links": [{"label": "Chat", "url": "http://localhost:8730/"}],
  "mock_base_url_port": 8731,
  "smoke": ["python", "-m", "v3.smoke"]
}
```
`processes` may be empty (v1). `smoke` exits 0 on success (one real turn against the running
stack). Launcher (platform): `./convo.sh {setup|start|stop|status|smoke|list} [v1 v2 ...|all]`
— `start` = ensure Ollama + model, register `common` defs + each version's defs (S2), start
the shared LLM worker if needed, start each version's processes (logs and pids under
`convo-agent/.run/`), start the hub. Starting `v2 v3` together must work.

## 4. Who owns what (no overlaps)

| Part | Owns |
|---|---|
| platform | `convo.sh`, `common/**`, `hub/**`, `requirements.txt`, `pytest.ini`, `.env.example`, `.gitignore`, `README.md`, `PRD.md` copy, Step-0 checks, Ollama lifecycle, `openspec/specs/platform/` |
| v1 | `v1/**`, `openspec/specs/v1/` |
| v2 | `v2/**` (incl. the reusable front door S5), Orkes API Gateway setup for v2, `openspec/specs/v2/` |
| v3 | `v3/**` (workflows, mock portfolio API + data, its web tweaks), `openspec/specs/v3/` |
| v4 | `v4/**` (local MCP server, Claude Desktop config, Orkes MCP Gateway setup), `openspec/specs/v4/` |
| v5 | `v5/**` (Agents SDK agent, AGENT-task workflow, its front door), `openspec/specs/v5/` |

A part needing a new Python dependency lists it in its design doc; platform's
`requirements.txt` includes it (known now: `conductor-python>=2,<3`, `requests`, `fastapi`,
`uvicorn`, `mcp`, `pytest`).

## Review decisions (binding)

1. **Loading the previous execution (v1–v5, S2/S4).** Workflows keep the PRD's optional
   `GET_WORKFLOW` task (ref `load_prev_ref`, input `workflowId: ${workflow.input.prevExecutionId}`,
   `optional: true`). S2 gains one placeholder, `"{{CONDUCTOR_API}}"`, replaced by
   `CONDUCTOR_SERVER_URL` (e.g. `http://localhost:8080/api`). When `.run/checks.json` reports
   `get_workflow: false`, the platform registrar's `prepare()` rewrites every `GET_WORKFLOW` task
   (anywhere, same recursion as the LLM rewrite) into an optional `HTTP` task with the same
   `taskReferenceName`: `GET {{CONDUCTOR_API}}/workflow/${workflow.input.prevExecutionId}?includeTasks=false`.
   Consumers pass `prev: "${load_prev_ref.output}"` and read `(.prev.response.body // .prev)` in JQ,
   so one workflow file works in both modes. Session check (correlationId == sessionId) stays in
   the version's JQ. Versions never write the HTTP form themselves.
2. **Playwright.** Platform lists `playwright` in `requirements.txt`; `./convo.sh setup` runs
   `python -m playwright install chromium`.
3. **v4 copies v3.** v4's workflows are written from S4 + design/v3.md if v3's files are not yet
   built; no build dependency between the parts.
4. **v5.** design/v5.md stands as written (Agents SDK agent, verify-first AGENT task with the
   reported SIMPLE `convo_v5_agent_run` fallback run by `python -m v5.worker --port 8751`,
   front door `python -m v2.server --version v5 --port 8750`). Its checks are added by the lead.
5. **Spec paths.** Specs live in `.cc/openspec/specs/<part>/spec.md` (harness convention); no
   conflicts between part specs were found.

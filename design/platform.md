# Platform design (convo-agent/ shared base)

## 1. Layout
```
convo-agent/convo.sh            bash launcher; thin: exports PYTHONPATH=., calls `python -m common.launcher "$@"`
convo-agent/common/__init__.py
  config.py      load(files=None): parse files (default [convo-agent/.env, <repo>/.env]) in order (KEY=VAL, # comments, quotes stripped), os.environ.setdefault each -> first file wins, real env always wins; get(key, default)
  conductor.py   S1 Conductor + ConductorError (requests only; no conductor-python dependency)
  register.py    prepare(wf: dict, mode: str, mock_port: int|None) -> dict (pure, deep copy: placeholders + LLM rewrite, S2; recurses into decisionCases/defaultCase/forkTasks/loopOver);
                 register_version(v), register_common() call prepare then the S1 client
  llm_mode.py    effective_mode(): CONVO_LLM_MODE or .run/llm_mode (written by checks) or "worker"
  llm_worker.py  chat(input: dict) -> dict (pure call to OLLAMA_URL, returns S3 output); `python -m common.llm_worker`: polls convo_llm_chat (S3)
  checks.py      `python -m common.checks`: Step-0 checks, prints table, writes .run/checks.json + .run/llm_mode
  ollama.py      ensure_running() via help-scripts start_ollama.sh; ensure_model(); stop()
  manifests.py   discover(): sorted glob v*/manifest.json -> list[dict]; select(args) ("all" or names)
  launcher.py    setup|start|stop|status|smoke|list|checks
  tasks/convo_llm_chat.json   task def (retryCount 2, FIXED, responseTimeout 120s)
  tests/         offline unit tests (pytest)
convo-agent/hub/server.py  stdlib http.server, `--port` (default 8700); hub/static/index.html (vanilla JS)
```

## 2. Conductor client (S1)
- Base = `CONDUCTOR_SERVER_URL` (default `http://localhost:8080/api`). Orkes: POST `/token` with key/secret, header `X-Authorization`, refresh on 401 once.
- `register_workflow`: PUT `/metadata/workflow` with `[wf]` (create-or-overwrite on both flavors).
- `run_sync`: OSS has no sync endpoint guarantee -> POST `/workflow/{name}` then poll `GET /workflow/{id}?includeTasks=false` every 0.25 s until terminal or `wait_seconds`. Orkes: use `POST /workflow/execute/{name}/1?waitForSeconds=` and fall back to polling.
- `search_by_correlation`: GET `/workflow/search?query=correlationId='x'[ AND workflowType='n']&size=&sort=startTime:DESC`, return `results`.
- `ui_url`: `CONDUCTOR_UI_URL` (default: server URL minus `/api`, OSS UI port 5000 if 8080) + `/execution/{id}` or `/search?correlationId=`.

## 3. LLM path
- Default model **`qwen2.5:3b`** (≈2 GB, reliable JSON with `format:"json"`); fallback `llama3.2:3b`. `CONVO_LLM_PROVIDER` default `ollama`.
- Worker: maps `messages[].message`→Ollama `content`; `options.temperature`, `num_predict=maxTokens`; `format:"json"` when `jsonOutput`; poll `/tasks/poll/convo_llm_chat?workerid=`, update via POST `/tasks`. Threads: 4.
- Mode decision (checks.py): register a one-task probe workflow `convo_platform_probe_llm` with native LLM_CHAT_COMPLETE (provider/model from env); run_sync 60 s. COMPLETED with non-empty `output.result` -> `native`, otherwise -> `worker` (reason recorded). `auto` resolves to that result.
- Other checks (each a tiny `convo_platform_probe_*` workflow, results in checks.json): GET_WORKFLOW reading a completed execution's `output`; GET_WORKFLOW on bogus id (does the task FAIL? — v1 needs `optional:true`); Switch not-taken branch: JQ referencing `${skipped_ref.output.x}` yields `null` (record actual value). Ollama reachable + model pulled.

## 4. Launcher
- `.run/<v>/<proc>.pid|.log`, `.run/llm_worker.pid|log`, `.run/hub.pid|log`. Start = `subprocess.Popen(cmd, cwd=convo-agent, env+PYTHONPATH, start_new_session=True)`; health = GET `http://localhost:<port><health>` up to 20 s.
- start order: ollama.ensure → checks (if no .run/llm_mode) → register_common → register_version each → llm_worker (once, if worker mode, ref-shared) → processes (skip if pid alive and port healthy: idempotent) → hub.
- stop vN: kill its pids (SIGTERM group, 5 s, SIGKILL); stop `all` also stops worker, hub, and Ollama (stop_ollama.sh) only if this launcher started it (`.run/ollama.started`).
- status prints table version/proc/pid/port/healthy; exit 0 always. smoke runs each manifest `smoke`, exits non-zero if any fails. list prints version, title, features. Unknown version → exit 2 with message.
- setup: `uv pip install -r requirements.txt` into the shared venv if missing, copy `.env.example`→`.env` if absent, ensure model.

## 5. Hub (8700)
- `GET /api/versions`: manifests + per-process `healthy` (live probe, 0.5 s timeout) + `running` bool; `GET /api/platform`: flavor, llm mode, model, checks.json. `GET /` page: card per version (title, summary, feature chips, status dot, links); "Version tour" table: rows = union of features, columns = versions, cell marks first version introducing a feature as **new**. Auto-refresh 5 s.
- Extra (usability): a platform strip at the top (flavor, LLM mode native/worker, model, Ollama up, failed Step-0 checks in red with the reason) and per-card "Start/Stop command" copy buttons (`./convo.sh start v3`) — the hub never spawns processes itself.

## 6. Interfaces the acceptance checks drive (keep stable)
- `common.config.load(files: list[str] | None = None)`; `get(key, default=None)` reads `os.environ` after load.
- `common.register.prepare(wf, mode, mock_port=None)` pure; never mutates its argument.
- `common.llm_worker.chat(input) -> {"result": ...}` reads `OLLAMA_URL` at call time (so a check can point it at a fake server).
- `python -m hub.server --port N`; `GET /api/versions` -> list of `{version,title,summary,features,links,processes:[{name,port,healthy}],running}`; `/` HTML contains the literal heading `Version tour`.
- `./convo.sh checks` (also run by `start` when `.run/llm_mode` is missing) writes `.run/checks.json` = `{"ollama":{ok,model}, "llm_native":{ok,reason}, "get_workflow":{ok,reason}, "get_workflow_missing":{ok,task_status}, "switch_not_taken":{ok,value}}` and `.run/llm_mode` (`native`|`worker`); exit 0 even when a probe fails (failure is data), non-zero only if Conductor is unreachable.
- Unknown version name in any command: stderr `unknown version: v9 (known: v1 v2 ...)`, exit 2.

## 7. Other files
requirements.txt: requests, fastapi, uvicorn, mcp, pytest, conductor-python>=2,<3. pytest.ini: `testpaths = common/tests v1/tests v2/tests v3/tests v4/tests v5/tests`, marker `live`, default `-m "not live"`. .gitignore: `.run/`, `.env`, `__pycache__/`. README: quick start, `./convo.sh start v2 v3`, demo script per version, troubleshooting.

## 8. As built (round 2, architect)
- Built: `convo.sh`, `common/{config,conductor,register,llm_mode,llm_worker,checks,ollama,manifests,launcher}.py`,
  `common/tasks/convo_llm_chat.json`, `requirements.txt`, `pytest.ini`, `.env.example`, `.gitignore`.
- Hub (round 3): `hub/server.py` (stdlib `ThreadingHTTPServer`, reads `common.manifests.discover()`, probes each
  process health in parallel with a 0.5 s timeout; `running` = has processes and all healthy; CLI-only versions get
  `cli: "python -m vN.chat"`), `GET /api/platform` = `{flavor, conductor_url, llm_mode, model, ollama_up, checks}`,
  `hub/static/index.html` (platform strip, version cards with start/stop copy buttons, Version tour table, 5 s refresh).
  `convo-agent/README.md`: per-version features, quick start, hub, ports, demo script per version, troubleshooting.
- Measured on this machine's Conductor OSS: `LLM_CHAT_COMPLETE` and `GET_WORKFLOW` are **unknown task types**
  (OSS queues them like SIMPLE tasks, they stay SCHEDULED). Step-0 probes stop after 4 s on a task stuck in
  SCHEDULED and record it as unsupported, so `./convo.sh checks` finishes in ~10 s. Result here:
  `llm_mode = worker`, `get_workflow.ok = false` → `prepare()` rewrites LLM tasks to `convo_llm_chat`
  and `GET_WORKFLOW` to the optional HTTP form (Review decision 1). `switch_not_taken.value = null`.
- `common.register.prepare(wf, mode, mock_port=None, get_workflow_ok=True)` (extra keyword; `register_version`
  passes the Step-0 result). Placeholders are replaced inside strings too (e.g. `"{{MOCK_BASE_URL}}/clients"`).
- `common.conductor.Conductor` also has `terminate(workflow_id)`.
- The launcher starts Ollama detached (`start_ollama.sh`) and waits ≤ 30 s for `/api/tags`.

# v5 — the same bot as a Conductor Agent (code path)

v1–v4 build the wealth-advisor bot with **no code**: workflow JSON, JQ, and an LLM task you can see
in the Conductor UI. v5 builds the same bot **in code** with the Conductor Agents SDK
(`conductor.ai.agents`). The audit trail is the same: every turn is a Conductor execution, found by
correlation id = session id.

| | no-code path (v1–v4) | code path (v5) |
|---|---|---|
| bot defined in | `vN/conductor/workflows/*.json` | `v5/agent.py` (`Agent(name="wealth_advisor", tools=[get_portfolio])`) |
| tools | HTTP task / Sub Workflow | `@tool get_portfolio` in `v5/tools.py` |
| called from a workflow | LLM_CHAT_COMPLETE task | AGENT task in `convo_v5_agent_turn` |
| memory | Get Workflow + JQ on the previous execution | same (`load_prev` + `build_memory` in `convo_v5_agent_turn`) |
| audit trail | execution link per turn | execution link per turn (`uiUrl`) |

## Files

- `agent.py` — the showcase: persona + `Agent(...)`, pointed at `CONVO_LLM_PROVIDER/CONVO_LLM_MODEL`.
- `tools.py` — `get_portfolio(client_name)` over `data/portfolios.json` (v5's own copy).
- `conductor/workflows/convo_v5_agent_turn.json` — Get Workflow (previous turn, optional) → JQ
  (history only from a COMPLETED run of the same session) → **AGENT** task → JQ save.
  Output: `reply, history, executionId, sessionId, restored, memorySource, memoryNote, agentMode, toolCalls`.
- `convo_v5_chat_turn.json` / `convo_v5_chat_history.json` — S4 adapters (Sub Workflow / Get Workflow)
  so the v2 web front door serves v5 unchanged.
- `probe.py` — verifies what the server supports; `worker.py` — the reported local fallback.
- `turn.py` — `run_turn` (starts the workflow) and `run_agent` (the local agent run).

## Verify first, then a reported fallback

`python -m v5.probe` prints `{aiEnabled, agentTask, sdkSessionMemory, agentMode, notes}`.
Result on a local Conductor OSS server:

| check | OSS (local) | Orkes |
|---|---|---|
| `aiEnabled` (Agents API answers) | true | true |
| `agentTask` (AGENT task runs `wealth_advisor`) | false — "Agent not found: wealth_advisor" | true once the agent is deployed |
| `sdkSessionMemory` | false (not relied on) | not relied on |
| `agentMode` | `local` | `server` |

When `agentTask` is false, the probe (run by `v5.worker` on start, and by every CLI turn) registers
the variant of `convo_v5_agent_turn` whose one agent task is SIMPLE `convo_v5_agent_run`, with the
same inputs. `python -m v5.worker` executes it: the same `Agent` (instructions + tools) driven against
Ollama, and the output says `agentMode: "local"`. Memory never depends on the SDK: the workflow loads
it from the previous execution id (`memorySource: "explicit"`), or starts fresh and says why
(`memorySource: "none"`, `memoryNote`). If the agent fails, the workflow FAILS and the CLI exits 1.

## Run it

```bash
./convo.sh start v5          # registers workflows, starts web :8750 and worker :8751
open http://localhost:8750/   # chat page (v2 front door)
python -m v5.chat --session demo "My client is 55, retiring at 62"
python -m v5.chat --session demo "How many years left?"          # remembers: 7 years
python -m v5.chat --session demo "What's in Jane Doe's portfolio?"  # get_portfolio tool call
python -m v5.chat --session demo --interactive                    # REPL, /quit ends it
./convo.sh smoke v5           # probe + two turns; prints memorySource and agentMode
./convo.sh stop v5
```

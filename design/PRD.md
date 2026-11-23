# PRD: Conversational Agent Demo on Orkes Conductor

Nov 19, 2026 · @Mangat · **Rev 2**

Rev 2 changes: one execution per turn instead of a long-running loop; no Human task for chat input;
browser calls the Orkes API Gateway directly (no proxy); a "real work" step before customers see it;
MCP Gateway + Claude Desktop; Agents SDK moves to last. A devil's-advocate review is at the end.

## Overview

We will build a session-aware chat assistant on Orkes Conductor, in versions, where each version is a
working demo. The assistant remembers earlier turns, so a follow-up question uses the context of what
the LLM already said.

- **Demo theme:** wealth advisor assistant (fits wealth-management and financial services prospects).
- **Audience:** prospect architects and dev leads in presales demos; internal SE enablement.
- **One-line pitch:** "Conductor is the agent backbone: it holds the conversation, runs the work the
  conversation triggers, and serves it to any front door (web, Claude Desktop, code), on any LLM."
- **Owner:** Mangat Rai, Head of Presales Engineering.
- **Builder:** Mangat with Claude as coding assistant.

Items marked **Verify** are not confirmed in docs and must be checked in Step 0 or on first run.

## Goals and non-goals

**Goals**

- Multi-turn chat with memory, built mostly in the Orkes UI (no-code path).
- Conductor, not the LLM vendor and not the browser, owns the session state.
- Provider-agnostic: the same workflow runs on OpenAI, Anthropic or others; the swap is an input, not an edit.
- A session can be resumed later ("You left off here. Continue?").
- The conversation triggers real work (a lookup), visible as tasks. This is the "why Conductor" answer.
- The same workflows serve three front doors: web page (API Gateway), Claude Desktop (MCP Gateway), code (Agents SDK).

**Non-goals**

- No `previousResponseId` chaining. It works only on OpenAI / Azure OpenAI and keeps the conversation at the vendor.
- No external database for history. Add one only if a prospect has a real need (retention, GDPR delete, analytics).
- No production-grade UI, auth or multi-tenant design.
- No financial advice logic. The assistant is a demo persona only.

## Core design: one execution per turn

Each chat turn is one short execution of the workflow `chat_turn`. Turns are chained by ID:

```
turn 1: chat_turn(sessionId=S, prevExecutionId="",  message)  -> execution E1 (output: reply, history)
turn 2: chat_turn(sessionId=S, prevExecutionId=E1, message)  -> E2 reads E1's history with GET_WORKFLOW
turn 3: chat_turn(sessionId=S, prevExecutionId=E2, message)  -> E3 ...
```

- **State lives in Conductor.** Each execution's output holds the history so far. The client only holds two
  pointers: `sessionId` (a random UUID it made) and the last successful `executionId`.
- **Reads are by ID, not by search.** `GET_WORKFLOW` reads the previous execution directly, so there is no
  search-index lag.
- **Session view.** `correlationId` = `sessionId`, so all turns of a session are listed together in Orkes search.
- **Resume** = keep the two pointers and send the next turn. Nothing waits or times out between turns.
- **System prompt is not stored in history.** It is added fresh each turn from the input, so the persona can
  change and the trim never has to protect it.

Why not a long-running loop (Rev 1)? It needed a Human/Wait task per message, an idle timeout, a session cap and
polling, and an execution sat idle while the user thought. Its one advantage, the whole chat in one execution
view, is replaced by the correlationId search.

## Version roadmap

Each version builds on the previous one and must be demo-able alone. **Do not show customers before v3.**

| Version | What we add | Customer takeaway | Orkes features shown | Build path |
| --- | --- | --- | --- | --- |
| Step 0 | Platform checks (below) | — | — | UI + curl |
| v1 | `chat_turn` workflow: memory across executions, trim, provider via input | Conductor holds the session; every turn is auditable | Get Workflow, Switch, JSON JQ Transform, LLM Chat Complete, sync execution | UI |
| v2 | Chat web page calling the API Gateway; resume prompt | Real app, no backend code | API Gateway (routes, CORS, API key) | UI + one static HTML page |
| v3 | Portfolio lookup inside the turn | The chat does real work, visibly | Sub Workflow, HTTP task, LLM JSON output, Switch | UI |
| v4 | Same workflows as MCP tools in Claude Desktop | Conductor is the agent backbone | MCP Gateway | UI config |
| v5 | Same bot as a Conductor Agent (code path) | Developers get the same audit trail | Conductor Agents SDK, AGENT task | Python + UI |
| Later | Advisor handoff (Human task) or RAG, per prospect | Human-in-the-loop / real documents | Human task, LLM Search Index | UI |

## Step 0: platform checks (no demo)

1. One LLM Chat Complete task alone on the OpenAI integration and on the Anthropic integration, with a
   `system` role message.
2. `GET_WORKFLOW` on Developer Edition: read a completed execution's `output` by ID.
3. API Gateway and MCP Gateway are available on Developer Edition (and on the customer demo cluster).
4. How long completed executions are kept (resume depends on it).
5. `conductor.integrations.ai.enabled=true` on the cluster (needed for v5).
6. The app key has the roles needed to define and run these workflows (the current `.env` key is worker-role only).

## v1 spec: `chat_turn`

**Inputs:** `sessionId` (string, required), `prevExecutionId` (string, empty on turn 1), `message` (string),
`llmProvider` (default: our OpenAI integration), `model` (default: a small fast model),
`systemPrompt` (default: "You are a wealth advisor assistant. Be concise.").

**Start with** `correlationId` = `sessionId`.

| # | Task (ref name) | Type | Config |
| --- | --- | --- | --- |
| 1 | `has_prev_ref` | Switch | JS: `$.prev ? 'load' : 'new'` with `prev` = `${workflow.input.prevExecutionId}` |
| 1a | `load_prev_ref` (case `load`) | Get Workflow | `id` = `${workflow.input.prevExecutionId}`, `includeTasks` = false, **optional** = true |
| 2 | `build_ref` | JSON JQ Transform | Inputs `prev` = `${load_prev_ref.output.workflow}`, `sessionId`, `msg`, `sys` from workflow input. Query below. |
| 3 | `chat_ref` | LLM Chat Complete | `llmProvider` / `model` from input, `messages` = `${build_ref.output.result.messages}`, `temperature` 0.3, `maxTokens` 500 |
| 4 | `save_ref` | JSON JQ Transform | Append the user message and `reply` to `history`, keep the last 20 (query below) |

`build_ref` query (use the prior history only if it is a completed turn of the same session):

```jq
(if .prev != null and .prev.status == "COMPLETED" and .prev.input.sessionId == .sessionId
 then (.prev.output.history // []) else [] end) as $h
| { history: $h,
    restored: ($h | length > 0),
    messages: ([{"role":"system","message":.sys}] + $h + [{"role":"user","message":.msg}]) }
```

`save_ref` query:

```jq
(.history + [{"role":"user","message":.msg},{"role":"assistant","message":.reply}]) | .[-20:]
```

**Output:** `reply` = `${chat_ref.output.result}`, `history` = `${save_ref.output.result}`,
`executionId` = `${workflow.workflowId}`, `sessionId`, `restored` = `${build_ref.output.result.restored}`.

The history holds only user/assistant pairs, appended together, so the last 20 always start with a user message
(Anthropic needs this). Keep the trim size even.

**How to test in v1:** Run Workflow in the Orkes UI. Turn 1 with an empty `prevExecutionId`; copy the execution ID
into turn 2's input. A 20-line script does the same faster.

**Acceptance criteria**

- [ ] Turn 1: "My client is 55 and wants to retire at 62." Turn 2: "How many years does he have?" Answer says 7.
- [ ] Turn 3 refers back to turn 1 without the user repeating facts.
- [ ] Each execution shows the user message (input), the reply and the history (output).
- [ ] Searching by the session's correlationId lists every turn.
- [ ] After 25 turns, `history` has 20 entries and starts with a user message.
- [ ] Changing only `llmProvider` + `model` inputs to Anthropic works, with no workflow edit.
- [ ] A `prevExecutionId` from another session, or one that does not exist, starts fresh with `restored` = false.

## v2–v5 specs

### v2: chat page on the API Gateway

One static HTML page. No backend of our own.

- **Gateway service** `wealth-advisor`: auth = API key, CORS allowed origin = the page's origin, a concurrent
  execution limit.
  - `POST /chat` → `chat_turn`, sync, timeout 30 s. Body `{sessionId, prevExecutionId, message}`.
  - `GET /session` → `chat_history` (one Get Workflow + JQ), returns the stored history to redraw a resumed chat.
- **Page:**
  - New chat: `crypto.randomUUID()` as `sessionId`, empty pointer.
  - Send: call `/chat`, show a "typing" state, disable Send until the reply arrives. Store the returned
    `executionId` **only on success**. A failed turn is retried with the same pointer.
  - On load with a stored session: "You left off here. Continue?" → Continue redraws from `/session`; No starts new.
  - Subtle links to the current execution and to the session's search in the Orkes UI.
- **Serve the page** from `http://localhost` (not `file://`, which sends origin `null`). The gateway API key goes
  in a git-ignored config file, never in the repo.
- **Fallback:** if the gateway is not available on the cluster, or a prospect objects to a key in the browser,
  use a tiny Python proxy with `conductor-python` (it handles the JWT).

**Verify:** the gateway sets `correlationId` from the request (or the pre-request script can); what the route returns
when the workflow outruns the timeout; which identity the gateway runs workflows as (Get Workflow needs read access).

**Acceptance:** a prospect chats in the browser; reply under ~5 s per turn on a small model; reloading the page
offers to continue and the bot still remembers; the linked executions show the same turns.

### v3: the chat does real work

Add a portfolio lookup so the bot answers with data it could not know.

- New workflow `get_portfolio(clientName)`: HTTP task to a mock JSON file (served from this public repo's raw
  URL, so there is no infrastructure; Orkes Cloud cannot reach localhost). It is its own workflow so v4 can
  expose it as an MCP tool.
- In `chat_turn`, before the main LLM call: `route_ref` (LLM Chat Complete, `jsonOutput` = true) returns
  `{"intent":"portfolio"|"chat","clientName":...}`; a Switch runs `get_portfolio` as a Sub Workflow when needed;
  the result goes into the system message for this turn only (not into history).
- Alternative: native tool calling in LLM Chat Complete, if it exists. **Verify.** The router is more visible in
  the execution view, which suits the demo.

**Acceptance:** "What's in Jane Doe's portfolio?" answers with the mock numbers; the lookup is a visible sub-workflow;
a plain question makes no lookup.

### v4: MCP Gateway + Claude Desktop

- MCP service with two tools: `ask_wealth_advisor` → `chat_turn` and `get_portfolio` → `get_portfolio`.
  Input schemas from Conductor schemas.
- Claude Desktop connects to the service's "MCP Tool Remote Endpoint" (Streamable HTTP). **Verify** how:
  a custom connector (remote URL) or a local `mcp-remote` bridge that adds the API key header.
- The story: the same workflows behind the web page are now tools for any agent, with the same audit trail.

**Acceptance:** in Claude Desktop, asking about a client's portfolio calls the tool, and the call is a visible
execution in Orkes.

### v5: same bot as a Conductor Agent

Conductor Agents SDK in Python (`conductor-python` 2.0.0, `from conductor.ai.agents import Agent, AgentRuntime`).

1. `Agent(name="wealth_advisor", model="openai/gpt-4o-mini", instructions=...)`.
2. Run twice with the same `session_id`. The Python runtime finds the latest completed execution for that session
   (a free-text search) and injects its messages.
3. Deploy the agent and call it from a workflow with an AGENT task (`agentType` = `conductor`, `name`, `prompt`, `sessionId`).

**Known from the SDK source:** the session lookup runs in the Python client, not the server. It uses search (index
lag) and silently returns no history on any error. **Verify** that an AGENT task with `sessionId` gets memory at all.

**Acceptance:** run 1 "My client is 55, retiring at 62"; run 2 "How many years left?" answers 7; both runs
visible as executions.

## Environment

- Orkes Developer Edition: developer.orkescloud.com (later: the customer demo cluster).
- LLM integrations: one OpenAI and one Anthropic, for the provider swap.
- Orkes application key and secret, and a gateway API key. Store in 1Password, never in the repo or the PRD.
- Python 3.13 with `conductor-python` 2.0.0 (shared venv).

## Open questions (Verify)

- [ ] Step 0 items 2–6.
- [ ] A Switch branch not taken: does `${load_prev_ref.output.workflow}` resolve to null?
- [ ] API Gateway: correlationId from the request; behaviour past the timeout; run-as identity.
- [ ] MCP Gateway: how Claude Desktop authenticates (API key only; OAuth is not documented).
- [ ] LLM Chat Complete native tool calling (v3 alternative).
- [ ] AGENT task + `sessionId` memory (v5).
- [ ] Where Orkes Cloud documents encryption at rest for workflow data. Banks will ask where chat PII sits.

## Devil's-advocate review

| Challenge | Answer |
| --- | --- |
| "Why not let the browser send the history each turn?" | Then the browser owns state and the pitch is gone. It can also forge assistant turns (prompt injection). The browser sends only a pointer; history is read from Conductor. |
| "Execution IDs are guessable / leak, so I can read someone's chat." | IDs are UUIDs, and `build_ref` ignores history whose `sessionId` does not match. Demo-grade, not production auth. |
| "Two tabs or a double-click send two turns on the same pointer." | The chat forks; one branch is lost. The page disables Send while waiting. Acceptable for a demo. |
| "A turn fails halfway: is history lost?" | No. The client only moves its pointer after a successful turn; the retry reads the last good execution. |
| "Old executions get purged: resume breaks." | `load_prev_ref` is optional, so the turn starts fresh with `restored` = false and the page says so. Retention is a Step 0 check. |
| "The API key is in the browser." | Yes, visible to anyone with the page. Its reach is one gateway service with a concurrency limit, a CORS origin, a small model and low `maxTokens`. Rotate after demos. The proxy fallback exists. |
| "Banks will never expose the orchestrator to browsers." | Agreed. The gateway is the API layer; in production it sits behind their own auth. Position it that way. |
| "Sync calls time out on slow LLM responses." | Small model, `maxTokens` 500, 30 s route timeout. Measure in v1. |
| "Is a workflow engine overkill for chat memory?" | For memory alone, yes, and an architect will say so. v3 (real work) and v4 (one backbone, many front doors) are the answer. That is why customers wait for v3. |
| "Each execution stores the full history: duplication." | ≤ 20 messages per execution, a few KB each. Production would store only the turn's delta. |
| "The provider swap isn't really one change." | `llmProvider` and `model` are both inputs, so the swap is one start-input change. |
| "Claude Desktop calling a chatbot is chat-in-chat." | True for `ask_wealth_advisor` alone. The strong part is `get_portfolio`: Claude uses the same business workflow as the web bot. Lead with that. |
| "The SDK's session memory silently forgets." | Noted for v5. Our no-code path reads by ID and reports `restored`, so it never forgets silently. |

## Demo script (5 minutes, after v3)

1. Chat 3 turns in the web page; the bot uses earlier context. Ask for a client's portfolio; it answers with data.
2. Open Orkes: the session's turns side by side (correlationId search); one turn's history; the lookup sub-workflow.
3. Reload the page: "Continue?" The bot still remembers, because state lives in Conductor.
4. Start a new chat with Anthropic as the provider: same workflow, new vendor.
5. Optional: Claude Desktop calls `get_portfolio` through the MCP Gateway (v4); for developers, show v5.

## Sources

- [LLM Chat Complete reference](https://orkes.io/content/reference-docs/ai-tasks/llm-chat-complete): `role` + `message`, output `result`, `jsonOutput`; the caller passes history.
- [Get Workflow](https://orkes.io/content/reference-docs/operators/get-workflow): read another execution by ID.
- [Execute workflow synchronously](https://orkes.io/content/reference-docs/api/workflow/synchronous-workflow-execution): `waitForSeconds` max 60.
- [API Gateway](https://orkes.io/content/developer-guides/api-gateway): routes, API key / no auth, CORS, concurrency limit.
- [MCP Gateway](https://orkes.io/content/developer-guides/mcp-gateway): workflows as MCP tools, Streamable HTTP, API key / no auth.
- [Conductor Agents](https://orkes.io/content/devguide/ai/conductor-agents): AGENT task inputs incl. `sessionId`, server flag.
- [AI & LLM orchestration recipes](https://orkes.io/content/ai-cookbook/ai-llm-recipes): `previousResponseId` limits.
- `conductor-python` 2.0.0 source: `conductor/ai/agents/runtime/runtime.py` `_get_session_messages`.

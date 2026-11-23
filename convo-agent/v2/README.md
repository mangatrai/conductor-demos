# v2 — chat page on a gateway

v1's chat turn, now behind a web page. Every HTTP call runs one workflow **synchronously** and returns
its output; the page keeps only a pointer (`sessionId` + last good `executionId`) and Conductor keeps
the conversation.

```
./convo.sh start v2          # registers the workflows, starts the page on :8720
open http://localhost:8720/
./convo.sh smoke v2          # or: python -m v2.smoke
```

## What to show
1. Ask a starter question. Under each reply, **what Conductor did** lists every task (ref · type · ms).
2. Click **execution ↗**: the run in the Conductor UI (Switch → Get Workflow → JQ → LLM → JQ).
3. Click **session ↗**: a correlation-id search listing every turn of this chat.
4. Reload the page: **You left off here. Continue?** runs `convo_v2_chat_history`, which uses Get
   Workflow to read the history from the last turn (only if it belongs to the same session).
5. Switch the model in the header: the model is a workflow input, so nothing is re-registered.

## Pieces
| File | What it is |
|---|---|
| `conductor/workflows/convo_v2_chat_turn.json` | one chat turn (S4) |
| `conductor/workflows/convo_v2_chat_history.json` | resume: history of a finished turn, same session only |
| `server.py` | the front door: `/api/chat`, `/api/session`, `/api/config`, `/healthz` + the page. v3 and v5 reuse it with `--version v3`/`v5` |
| `web/` | the page (plain HTML/JS/CSS, no build) |
| `gateway/` | the Orkes API Gateway service with the same routes (`python -m v2.gateway.setup_gateway --dry-run`) |
| `smoke.py` | two turns + resume against the running stack |

Front-door errors: `400` bad body, `502` workflow failed or Conductor unreachable, `504` still running
after 30 s (the response carries the `executionId` so you can open it).

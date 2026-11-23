# v3: chat that does real work (portfolio lookup)

The bot from v1/v2, plus one new ability: when you ask about a client, it looks up that client's
portfolio from an API and answers with the actual numbers.

## Run
```
./convo.sh start v3        # registers workflows, starts web (8730) + mock API (8731)
open http://localhost:8730/
python -m v3.chat          # terminal chat (/new, /quit; --resume)
python -m v3.smoke         # one portfolio turn + one plain turn
python -m v3.mock_api --port 8731 --fail   # demo "API down"
```

## Which Conductor feature does what
| Task in `convo_v3_chat_turn` | Feature | Why |
|---|---|---|
| `has_prev_ref` → `load_prev_ref` | Switch (javascript) + Get Workflow | memory: load the previous turn only when there is one |
| `hist_ref`, `norm_ref`, `ctx_ref`, `save_ref` | JSON JQ Transform | restore and save history, clean up the router answer, build the prompt |
| `route_ref` | LLM Chat Complete with `jsonOutput` | the LLM decides `{"intent","clientName"}` |
| `need_lookup_ref` | Switch (value-param) | run the lookup only for `intent == "portfolio"` |
| `lookup_ref` | Sub Workflow `convo_v3_get_portfolio` | reusable tool (v4 exposes it over MCP) |
| `http_ref` (inside the sub workflow) | HTTP task, optional, 1 retry | call the portfolio API; failures never fail the turn |
| `chat_ref` | LLM Chat Complete | the answer, grounded in the lookup result |

The lookup result goes into the system prompt only. It is **never** saved to history.
Output adds `lookup`: `null`, or `{clientName, found, error, subWorkflowId, totalValue}`.

## 5-minute demo
1. "What's in Jane Doe's portfolio?" → $1,250,000, YTD 6.4%. The card links to the sub workflow.
2. "and how did she do this year?" → the router uses history to work out who "she" is.
3. "What is a Roth IRA?" → no lookup (the Switch takes the default branch).
4. "What's in Zelda Quimby's portfolio?" → not found, and the bot lists the known clients.
5. Restart the mock with `--fail` → the bot says the data is temporarily unavailable. The turn still COMPLETES.

## Troubleshooting
- Lookup always "unavailable": the mock is not on 8731 (`curl localhost:8731/clients`).
- Turn stuck: check Ollama (`curl localhost:11434/api/tags`) and `.run/llm_mode`.

# Orkes API Gateway for v2

`wealth_advisor_service.json` describes the `wealth-advisor` service: API-key auth, CORS for
`http://localhost:8720`, concurrency limit 5, and two routes that each run one workflow synchronously:

| Route | Workflow | Mode |
|---|---|---|
| `POST /chat` | `convo_v2_chat_turn` (correlationId = `sessionId`) | sync, 30 s |
| `GET /session` | `convo_v2_chat_history` | sync |

```
python -m v2.gateway.setup_gateway --dry-run   # print the definition only
python -m v2.gateway.setup_gateway             # on Orkes: create or update the service
```

On Conductor OSS the script only prints the definition: the API Gateway is Orkes-only, and the local
front door (`python -m v2.server`, port 8720) stands in with the same routes under `/api`.

**Verify:** the gateway REST path (`/gateway/config/service`) and field names differ between Orkes
releases. Check them in your cluster's Swagger (`<cluster>/swagger-ui`) or create the service once in the
UI (API Gateway → Services) and compare the exported JSON with this file.

To point the page at the gateway, create `v2/web/config.local.json` (git-ignored):
`{"apiBase": "https://<cluster>/gateway/wealth-advisor", "apiKey": "<key>"}`.

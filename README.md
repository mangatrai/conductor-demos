# Conductor demos

A collection of self-contained [Orkes Conductor](https://orkes.io) demos and labs. Each folder is
standalone with its own README, workflow definitions, workers and scripts.

| Folder | What it shows |
|---|---|
| [`dispute_demo/`](dispute_demo/) | Credit card dispute workflow: one dispute fans out to one case per charge (FORK_JOIN_DYNAMIC), the parent closes last. BUSINESS_RULE triage, retries, WAIT for the merchant, HUMAN analyst review with a request-info loop. FastAPI cardholder portal, analyst console and card-network simulator. |
| [`labs/`](labs/) | Small single-file worker experiments. |

## Setup shared by all demos

- Python 3.13 venv with `conductor-python` (see [`AGENTS.md`](AGENTS.md)); extra packages per demo in its `requirements.txt`.
- A local, git-ignored `.env` at this root:

```
CONDUCTOR_SERVER_URL=https://<your-cluster>/api
CONDUCTOR_AUTH_KEY=...
CONDUCTOR_AUTH_SECRET=...
```

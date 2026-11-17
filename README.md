# Conductor demos

A collection of self-contained [Orkes Conductor](https://orkes.io) demos and labs. Each folder is
standalone with its own README, workflow definitions, workers and scripts.

| Folder | What it shows |
|---|---|
| [`dispute_demo/`](dispute_demo/) | Credit card dispute workflow: one dispute fans out to one case per charge (FORK_JOIN_DYNAMIC), the parent closes last. BUSINESS_RULE triage, retries, WAIT for the merchant, HUMAN analyst review with a request-info loop. FastAPI cardholder portal, analyst console and card-network simulator. |
| [`labs/`](labs/) | Small single-file worker experiments. |

## Quick start

```bash
git clone https://github.com/mangatrai/conductor-demos.git
cd conductor-demos
cp .env.example .env      # fill in your Orkes cluster URL and application access key
./dispute_demo/start.sh   # each demo has its own start script and README
```

All demos share one `.env` at the repository root (git-ignored) and, by default, one Python virtualenv at `.venv`.
See each demo's README for prerequisites and a step-by-step walkthrough.

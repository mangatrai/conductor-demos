# Conductor demos

Self-contained examples built on [Orkes Conductor](https://orkes.io). Each folder is standalone, with its own README,
workflow definitions, workers and scripts.

| Folder | What it shows |
|---|---|
| [`dispute_demo/`](dispute_demo/) | A card issuer's dispute process. One dispute fans out to one case per charge, and the dispute closes only after its last case. Decision-table triage, automatic retries with an operations queue, merchant and cardholder waits, analyst review with a question-and-answer loop, and charges added to an open dispute. Includes a one-screen web console. Runs on Orkes Conductor and on Conductor OSS 3.34+. |
| [`labs/`](labs/) | Small single-file worker exercises. |

## Quick start

```bash
git clone https://github.com/mangatrai/conductor-demos.git
cd conductor-demos
cp .env.example .env      # set CONDUCTOR_FLAVOR, the server URL and (for Orkes) the access key
./dispute_demo/start.sh   # or run it as a container; see the demo's README
```

All examples share one `.env` at the repository root (git-ignored) and, by default, one Python virtualenv at `.venv`.
See each folder's README for prerequisites and an end-to-end walkthrough.

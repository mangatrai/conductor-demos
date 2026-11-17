# Conductor Workers — Agent Guide

Multi-project workspace for Conductor (Orkes) workers and related code. Each worker or
project lives in its own subfolder under this directory.

## Paths

| What | Path |
|------|------|
| Project root | `/Users/mrai/sandbox/castles/conductor` |
| Shared Python venv (uv) | `/Users/mrai/.uv/venvs/conductor` |
| Python interpreter | `/Users/mrai/.uv/venvs/conductor/bin/python` |

## Python environment (uv)

- One shared uv-managed venv for all subprojects: `/Users/mrai/.uv/venvs/conductor`
- Python **3.13** (conductor-python supports 3.10–3.14; do not use 3.15).
- Installed: `conductor-python` (Conductor Python SDK, import as `conductor.client`).

Activate:

```bash
source /Users/mrai/.uv/venvs/conductor/bin/activate
```

Install / add packages (always via uv, into this venv — never system pip):

```bash
uv pip install --python /Users/mrai/.uv/venvs/conductor <package>
# or, with the venv activated:
uv pip install <package>
```

Run without activating (preferred for agents, since shell state does not persist):

```bash
/Users/mrai/.uv/venvs/conductor/bin/python path/to/worker.py
# or
VIRTUAL_ENV=/Users/mrai/.uv/venvs/conductor uv run --active python path/to/worker.py
```

Recreate from scratch if needed:

```bash
uv venv /Users/mrai/.uv/venvs/conductor --python 3.13
uv pip install --python /Users/mrai/.uv/venvs/conductor conductor-python
```

## Conventions

- Do **not** create per-subfolder venvs unless a subproject has conflicting dependencies;
  if it does, document it in that subfolder's own `AGENTS.md`.
- If a subproject needs extra packages, list them in a `requirements.txt` in that subfolder
  and install into the shared venv with `uv pip install -r <subfolder>/requirements.txt`.
- Conductor server connection is configured via env vars read by the SDK:
  `CONDUCTOR_SERVER_URL` (e.g. `https://<host>/api`), `CONDUCTOR_AUTH_KEY`,
  `CONDUCTOR_AUTH_SECRET`. Never commit credentials; use a local `.env` that is git-ignored.

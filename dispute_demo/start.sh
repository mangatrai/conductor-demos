#!/usr/bin/env bash
# One command to run the dispute demo:
#   ./start.sh            set up, register in Orkes, reset demo data, start app + workers
#   ./start.sh --keep     same, but keep existing demo data and executions (no reset)
#   PORT=9000 ./start.sh  use another port
# Stop with Ctrl+C.
set -euo pipefail

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$DEMO_DIR")"
cd "$DEMO_DIR"

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

# 1. Python: $PYTHON, else the active virtualenv, else <repo>/.venv (created on first run)
step "Python environment"
if [[ -n "${PYTHON:-}" ]]; then
  PY="$PYTHON"
elif [[ -n "${VIRTUAL_ENV:-}" ]]; then
  PY="$VIRTUAL_ENV/bin/python"
else
  VENV="$REPO_DIR/.venv"
  if [[ ! -x "$VENV/bin/python" ]]; then
    if command -v uv >/dev/null 2>&1; then
      uv venv --quiet --python 3.13 "$VENV"
    else
      BASE_PY="$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3.10 || command -v python3 || true)"
      [[ -z "$BASE_PY" ]] && { echo "Python 3.10+ not found. Install it (or uv: https://docs.astral.sh/uv/) and retry."; exit 1; }
      "$BASE_PY" -m venv "$VENV"
    fi
  fi
  PY="$VENV/bin/python"
fi
"$PY" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"' || exit 1
echo "  using $("$PY" --version) at $PY"

# 2. Dependencies (fast no-op when already installed)
step "Installing requirements"
if command -v uv >/dev/null 2>&1; then
  uv pip install --quiet --python "$PY" -r requirements.txt
else
  "$PY" -m pip install --quiet --disable-pip-version-check -r requirements.txt
fi
echo "  ok"

# 3. Credentials and connectivity
step "Checking Orkes connection (.env at $REPO_DIR/.env)"
"$PY" scripts/check_setup.py

# 4. Task definitions, forms, workflows
step "Saving the triage decision rule and registering definitions, forms and workflows in Orkes"
"$PY" scripts/register.py

# 5. Fresh demo data
if [[ "${1:-}" != "--keep" ]]; then
  step "Resetting demo data (terminates and removes previous dispute_* executions)"
  "$PY" scripts/reset_demo.py --purge
fi

# 6. Run
step "Starting web app + workers (Ctrl+C to stop)"
exec "$PY" run.py --port "${PORT:-8000}"

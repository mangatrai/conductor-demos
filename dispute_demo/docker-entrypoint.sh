#!/usr/bin/env bash
# Container start: same steps as start.sh, minus the Python setup (done at build time).
set -euo pipefail
cd /app

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

step "Checking the Conductor connection"
python scripts/check_setup.py

step "Registering triage rules, task definitions, forms and workflows"
python scripts/register.py

if [[ "${KEEP_DATA:-0}" != "1" ]]; then
  step "Resetting demo data (terminates and removes previous dispute_* executions)"
  python scripts/reset_demo.py --purge
fi

step "Starting web app + workers (Ctrl+C to stop)"
exec python run.py --port "${PORT:-8000}"

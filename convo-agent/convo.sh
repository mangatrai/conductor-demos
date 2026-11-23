#!/usr/bin/env bash
# One launcher for every version: ./convo.sh {setup|start|stop|status|smoke|list|checks} [v1 v2 ...|all]
cd "$(dirname "$0")" || exit 1
# The python3 of your activated virtual environment (README: Quick start); CONVO_PYTHON overrides it.
PY="${CONVO_PYTHON:-$(command -v python3)}"
[ -n "$PY" ] || { echo "python3 not found: create and activate a virtual environment first (see README.md)" >&2; exit 1; }
# setup installs requirements.txt here, before the launcher runs: the launcher itself imports them.
if [ "${1:-}" = "setup" ]; then
  if command -v uv >/dev/null 2>&1; then
    uv pip install -q --python "$PY" -r requirements.txt || exit 1
  else
    "$PY" -m pip install -q -r requirements.txt || exit 1
  fi
fi
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -m common.launcher "$@"

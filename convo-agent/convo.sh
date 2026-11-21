#!/usr/bin/env bash
# One launcher for every version: ./convo.sh {setup|start|stop|status|smoke|list|checks} [v1 v2 ...|all]
cd "$(dirname "$0")" || exit 1
PY="${CONVO_PYTHON:-/Users/mrai/.uv/venvs/conductor/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3)"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -m common.launcher "$@"

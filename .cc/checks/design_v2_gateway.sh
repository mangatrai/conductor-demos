#!/usr/bin/env bash
# v2: gateway setup --dry-run prints service, routes, stand-in notice; exit 0
PY=/Users/mrai/.uv/venvs/conductor/bin/python
[ -x "$PY" ] || PY=$(command -v python3)
[ -d convo-agent ] || { echo "FAIL: convo-agent/ missing"; exit 1; }
cd convo-agent || exit 1
out=$("$PY" -m v2.gateway.setup_gateway --dry-run 2>&1 </dev/null)
rc=$?
[ $rc -eq 0 ] || { echo "FAIL: setup_gateway --dry-run exited $rc: $(echo "$out" | tail -1)"; exit 1; }
echo "$out" | grep -q "wealth-advisor" || { echo "FAIL: no wealth-advisor service in output"; exit 1; }
echo "$out" | grep -q "/chat" || { echo "FAIL: route /chat missing"; exit 1; }
echo "$out" | grep -q "/session" || { echo "FAIL: route /session missing"; exit 1; }
echo "$out" | grep -qi "stand-in\|stand in\|standin" || { echo "FAIL: stand-in notice missing"; exit 1; }
echo "PASS"

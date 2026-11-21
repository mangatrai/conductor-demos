#!/usr/bin/env bash
# v4: convo.sh start v4 -> status shows mcp+mock healthy -> convo.sh smoke v4 exits 0.
# The launcher owns v4's ports (8740 mcp, 8741 mock) per the contract; no override exists.
cd "$(dirname "$0")/../.." || exit 1
fail() { echo "FAIL: $1"; exit 1; }
[ -x convo-agent/convo.sh ] || [ -f convo-agent/convo.sh ] || fail "convo-agent/convo.sh missing"
cd convo-agent || fail "no convo-agent dir"
cleanup() { bash ./convo.sh stop v4 >/dev/null 2>&1; }
trap cleanup EXIT

# bounded run helper: run "$@" with deadline in seconds, output to $OUT
run_bounded() {
  local secs=$1; shift
  "$@" >"$OUT" 2>&1 &
  local pid=$! i=0
  while kill -0 "$pid" 2>/dev/null; do
    [ "$i" -ge $((secs*2)) ] && { kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; return 124; }
    sleep 0.5; i=$((i+1))
  done
  wait "$pid"
}
OUT=$(mktemp "${TMPDIR:-/tmp}/v4chk.XXXXXX")

run_bounded 150 bash ./convo.sh start v4; rc=$?
[ $rc -eq 0 ] || fail "convo.sh start v4 exit $rc: $(tail -n 2 "$OUT" | tr '\n' ' ')"

run_bounded 30 bash ./convo.sh status v4; rc=$?
[ $rc -eq 0 ] || fail "convo.sh status v4 exit $rc"
ST=$(cat "$OUT")
echo "$ST" | grep -i 'v4' | grep -qi 'mcp' || fail "status shows no v4 mcp row"
echo "$ST" | grep -i 'v4' | grep -qi 'mock' || fail "status shows no v4 mock row"
for p in mcp mock; do
  line=$(echo "$ST" | grep -i 'v4' | grep -i "$p" | head -n1)
  echo "$line" | grep -qiE 'unhealthy|not healthy|down|false|no[[:space:]]*$|✗' && fail "v4 $p not healthy: $line"
  echo "$line" | grep -qiE 'healthy|true|yes|up|ok|✓' || fail "v4 $p not shown healthy: $line"
done

# independent confirmation with bounded HTTP probes
command -v curl >/dev/null || fail "curl missing"
curl -fsS -m 5 http://localhost:8740/healthz >/dev/null || fail "v4 MCP /healthz not answering"
curl -fsS -m 5 http://localhost:8741/healthz >/dev/null || fail "v4 mock /healthz not answering"

run_bounded 240 bash ./convo.sh smoke v4; rc=$?
[ $rc -eq 0 ] || fail "convo.sh smoke v4 exit $rc: $(tail -n 2 "$OUT" | tr '\n' ' ')"
rm -f "$OUT"
echo "PASS"

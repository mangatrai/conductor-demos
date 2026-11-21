#!/usr/bin/env bash
# v5: launcher smoke passes; probe reports server features
cd "$(dirname "$0")/../.." || exit 1
fail() { echo "FAIL: $1"; exit 1; }
[ -d convo-agent ] && [ -x convo-agent/convo.sh ] || fail "convo-agent/convo.sh missing or not executable"
cd convo-agent || exit 1
PY=/Users/mrai/.uv/venvs/conductor/bin/python
[ -x "$PY" ] || PY=python3
OUT="${TMPDIR:-/tmp}/v5launch.$$"
mkdir -p "$OUT"
cleanup() { ./convo.sh stop v5 >/dev/null 2>&1; rm -rf "$OUT"; }
trap cleanup EXIT

# bounded runner: run_to SECONDS OUTFILE cmd...
run_to() {
  "$PY" -I - "$@" <<'PYEOF'
import subprocess, sys
secs, outf, cmd = int(sys.argv[1]), sys.argv[2], sys.argv[3:]
try:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=secs)
    open(outf, "w").write(r.stdout + r.stderr)
    sys.exit(r.returncode)
except subprocess.TimeoutExpired:
    open(outf, "w").write("timed out")
    sys.exit(124)
PYEOF
}

run_to 240 "$OUT/start" ./convo.sh start v5 || fail "convo.sh start v5 failed: $(tail -n 2 "$OUT/start" | tr '\n' ' ')"
run_to 420 "$OUT/smoke" ./convo.sh smoke v5 || fail "convo.sh smoke v5 nonzero: $(tail -n 2 "$OUT/smoke" | tr '\n' ' ')"
grep -q "memorySource" "$OUT/smoke" || fail "smoke output lacks memorySource"
grep -q "agentMode" "$OUT/smoke" || fail "smoke output lacks agentMode"

run_to 120 "$OUT/probe" env PYTHONPATH=. "$PY" -m v5.probe || fail "python -m v5.probe failed: $(tail -n 2 "$OUT/probe" | tr '\n' ' ')"
"$PY" -I - "$OUT/probe" <<'PYEOF' || fail "probe JSON invalid (need boolean aiEnabled, agentTask, sdkSessionMemory)"
import json, sys
txt = open(sys.argv[1]).read()
d = None
dec = json.JSONDecoder()
for i, c in enumerate(txt):
    if c == "{":
        try:
            d, _ = dec.raw_decode(txt[i:])
            break
        except ValueError:
            pass
assert isinstance(d, dict)
for k in ("aiEnabled", "agentTask", "sdkSessionMemory"):
    assert isinstance(d.get(k), bool), k
PYEOF
echo "PASS"

#!/usr/bin/env bash
# Check: convo.sh list / start v9 / status all
cd "$(dirname "$0")/../.." || exit 1
PY=/Users/mrai/.uv/venvs/conductor/bin/python
[ -x "$PY" ] || PY=$(command -v python3) || { echo "FAIL: no python"; exit 1; }
[ -f convo-agent/convo.sh ] || { echo "FAIL: convo-agent/convo.sh missing"; exit 1; }
exec "$PY" -I - <<'PYEOF'
import glob, json, os, shutil, socket, subprocess, sys

ROOT = os.getcwd()
APP = os.path.join(ROOT, "convo-agent")

def fail(msg):
    print("FAIL: " + msg.replace("\n", " ")[:300])
    sys.exit(1)

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def run(*args):
    try:
        r = subprocess.run(["bash", "convo.sh", *args], cwd=APP, capture_output=True,
                           text=True, timeout=60, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        fail("convo.sh %s did not finish in 60s" % " ".join(args))
    return r.returncode, r.stdout + r.stderr

created = []
try:
    if not glob.glob(os.path.join(APP, "v*", "manifest.json")):
        for i, v in enumerate(["v1", "v2"]):
            d = os.path.join(APP, v)
            if os.path.exists(d):
                fail("%s exists without manifest; cannot fake" % v)
            os.makedirs(d); created.append(d)
            procs = [] if v == "v1" else [{"name": "web", "cmd": ["true"], "port": free_port(), "health": "/healthz"}]
            json.dump({"version": v, "title": "Fake title %s zq" % v, "summary": "s",
                       "features": ["FeatureAlpha%s" % v, "FeatureBeta%s" % v],
                       "processes": procs, "links": [], "smoke": ["true"]},
                      open(os.path.join(d, "manifest.json"), "w"))
    manifests = []
    for f in sorted(glob.glob(os.path.join(APP, "v*", "manifest.json"))):
        manifests.append(json.load(open(f)))
    if not manifests:
        fail("no manifests")

    rc, out = run("list")
    if rc != 0:
        fail("list exit %d: %s" % (rc, out))
    for m in manifests:
        if m["version"] not in out:
            fail("list lacks version %s" % m["version"])
        if m["title"] not in out:
            fail("list lacks title of %s" % m["version"])
        for ft in m.get("features", []):
            if ft not in out:
                fail("list lacks feature %r of %s" % (ft, m["version"]))

    rc, out = run("start", "v9")
    if rc == 0:
        fail("start v9 exited 0")
    if "v9" not in out:
        fail("start v9 error does not name v9: " + out)

    rc, out = run("status", "all")
    if rc != 0:
        fail("status all exit %d: %s" % (rc, out))
    lines = out.splitlines()
    for m in manifests:
        for p in m.get("processes", []):
            rows = [l for l in lines if m["version"] in l and str(p["port"]) in l]
            if not rows:
                fail("status has no row with %s and port %s" % (m["version"], p["port"]))
finally:
    for d in created:
        shutil.rmtree(d, ignore_errors=True)
print("OK")
PYEOF

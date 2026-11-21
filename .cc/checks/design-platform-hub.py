import glob, json, os, socket, subprocess, sys, time, urllib.request

def fail(m):
    print("FAIL: " + m); sys.exit(1)

root = os.path.join(os.getcwd(), "convo-agent")
if not os.path.isdir(root):
    fail("convo-agent/ missing")
manifests = sorted(glob.glob(os.path.join(root, "v*", "manifest.json")))
if not manifests:
    fail("no v*/manifest.json found")
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
p = subprocess.Popen([sys.executable, "-m", "hub.server", "--port", str(port)], cwd=root,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def get(path):
    return urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5).read().decode()
try:
    deadline = time.time() + 30
    body = None
    while time.time() < deadline:
        if p.poll() is not None:
            fail("hub exited early")
        try:
            body = get("/api/versions"); break
        except Exception:
            time.sleep(0.5)
    if body is None:
        fail("hub did not answer /api/versions in 30s")
    data = json.loads(body)
    if isinstance(data, dict):
        data = data.get("versions", data)
    if not isinstance(data, list):
        fail("/api/versions is not a list")
    if len(data) != len(manifests):
        fail(f"expected {len(manifests)} entries, got {len(data)}")
    for e in data:
        for k in ("title", "features", "running"):
            if k not in e:
                fail(f"entry missing {k}: {e}")
        if not isinstance(e["features"], list) or not e["features"]:
            fail("features must be a non-empty list")
    page = get("/")
    if "Version tour" not in page:
        fail("page / lacks 'Version tour'")
finally:
    p.terminate()
    try: p.wait(5)
    except Exception: p.kill()
print("OK")

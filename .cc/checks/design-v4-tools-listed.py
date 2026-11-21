import json, os, socket, subprocess, sys, time, urllib.request, urllib.error

def fail(msg):
    print("FAIL: " + msg)
    sys.exit(1)

s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
cwd = os.path.join(os.getcwd(), "convo-agent")
if not os.path.isdir(cwd):
    fail("convo-agent/ directory does not exist")
proc = subprocess.Popen(
    ["/Users/mrai/.uv/venvs/conductor/bin/python", "-m", "v4.mcp_server", "--transport", "http", "--port", str(port)],
    cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
url = f"http://127.0.0.1:{port}/mcp"
hdrs = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

def rpc(body, sid=None):
    h = dict(hdrs)
    if sid:
        h["Mcp-Session-Id"] = sid
    req = urllib.request.Request(url, json.dumps(body).encode(), h)
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read().decode()
        sid2 = r.headers.get("Mcp-Session-Id") or sid
    if not raw.strip():
        return None, sid2
    for line in raw.splitlines():
        if line.startswith("data:"):
            raw = line[5:].strip(); break
    return json.loads(raw), sid2

try:
    deadline = time.time() + 30
    init = None
    while time.time() < deadline:
        if proc.poll() is not None:
            fail("v4 MCP server exited early with code %s" % proc.returncode)
        try:
            init, sid = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "check", "version": "0"}}})
            break
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.5)
    if init is None:
        fail("MCP server did not answer initialize at /mcp within 30s")
    rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    res, _ = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, sid)
    tools = {t["name"]: t for t in res["result"]["tools"]}
    for name, req_arg in (("ask_wealth_advisor", "message"), ("get_portfolio", "clientName")):
        if name not in tools:
            fail(f"tool {name} not listed (got {sorted(tools)})")
        schema = tools[name].get("inputSchema", {})
        if req_arg not in schema.get("required", []):
            fail(f"{name} does not require {req_arg}")
finally:
    proc.terminate()
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        proc.kill()
print("OK")

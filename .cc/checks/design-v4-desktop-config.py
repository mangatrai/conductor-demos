import glob, json, os, sys

def fail(m):
    print("FAIL: " + m); sys.exit(1)

def load(p):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception as e:
        fail("invalid JSON %s: %s" % (p, e))

d = "convo-agent/v4/claude_desktop"
if not os.path.isdir(d):
    fail("missing dir " + d)
files = sorted(glob.glob(d + "/*.json"))
if not files:
    fail("no JSON configs in " + d)

stdio_ok = remote_ok = False
for p in files:
    servers = load(p).get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        continue
    for s in servers.values():
        if not isinstance(s, dict) or not s.get("command"):
            continue
        args = [str(a) for a in s.get("args", [])]
        joined = " ".join([str(s["command"])] + args)
        if "v4.mcp_server" in joined and "stdio" in args:
            stdio_ok = True
        if "mcp-remote" in joined and "http://localhost:8740/mcp" in args:
            remote_ok = True
if not stdio_ok:
    fail("no stdio config running v4.mcp_server --transport stdio")
if not remote_ok:
    fail("no remote config using mcp-remote to http://localhost:8740/mcp")

g = "convo-agent/v4/gateway"
sp = g + "/orkes_mcp_service.json"
if not os.path.isfile(sp):
    fail("missing " + sp)
data = load(sp)
tools = None
def find(o):
    global tools
    if isinstance(o, dict):
        for k, v in o.items():
            if k.lower() in ("tools", "mcptools") and isinstance(v, list):
                tools = v; return
            find(v)
    elif isinstance(o, list):
        for v in o: find(v)
find(data)
if tools is None and isinstance(data, list):
    tools = data
if not tools or len(tools) != 2:
    fail("orkes_mcp_service.json must define exactly two tools")
if not os.path.isfile(g + "/SETUP.md"):
    fail("missing " + g + "/SETUP.md")
print("OK")

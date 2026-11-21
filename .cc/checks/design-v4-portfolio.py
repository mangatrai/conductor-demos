import asyncio, json, os, subprocess, sys, urllib.request

ROOT = os.getcwd()
APP = os.path.join(ROOT, "convo-agent")
MCP_URL = "http://localhost:8740/mcp"
API = os.environ.get("CONDUCTOR_SERVER_URL", "http://localhost:8080/api").rstrip("/")


def fail(msg):
    print("FAIL: " + msg)
    sys.exit(1)


def launcher(*args, t=240):
    return subprocess.run(["./convo.sh", *args], cwd=APP, capture_output=True, text=True, timeout=t)


async def call():
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    async with streamablehttp_client(MCP_URL, timeout=30) as (r, w, _):
        async with ClientSession(r, w) as s:
            await asyncio.wait_for(s.initialize(), 30)
            tools = [t.name for t in (await asyncio.wait_for(s.list_tools(), 30)).tools]
            if "get_portfolio" not in tools:
                fail("get_portfolio tool missing, got %s" % tools)
            return await asyncio.wait_for(s.call_tool("get_portfolio", {"clientName": "Jane Doe"}), 90)


def main():
    if not os.path.exists(os.path.join(APP, "convo.sh")):
        fail("convo-agent/convo.sh does not exist")
    try:
        p = launcher("start", "v4")
        if p.returncode != 0:
            fail("convo.sh start v4 exit %d: %s" % (p.returncode, (p.stderr or p.stdout).strip()[-200:]))
        try:
            res = asyncio.run(asyncio.wait_for(call(), 150))
        except SystemExit:
            raise
        except BaseException as e:
            fail("MCP call failed: %r" % (e,))
        if res.isError:
            fail("get_portfolio returned isError")
        sc = res.structuredContent or {}
        text = " ".join(getattr(c, "text", "") for c in res.content)
        blob = json.dumps(sc) + " " + text
        if "holdings" not in blob:
            fail("result has no holdings")
        if "Execution:" not in text and not sc.get("uiUrl"):
            fail("result has no execution link")
        eid = sc.get("executionId")
        if not eid:
            fail("structuredContent has no executionId")
        try:
            with urllib.request.urlopen(API + "/workflow/" + eid, timeout=20) as r:
                wf = json.load(r)
        except Exception as e:
            fail("cannot fetch execution %s: %r" % (eid, e))
        if wf.get("status") != "COMPLETED":
            fail("execution status %s" % wf.get("status"))
        if wf.get("workflowName") != "convo_v4_get_portfolio":
            fail("execution is %s" % wf.get("workflowName"))
        print("OK")
    finally:
        try:
            launcher("stop", "v4", t=60)
        except Exception:
            pass


main()

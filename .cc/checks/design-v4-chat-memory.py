import asyncio, json, os, socket, subprocess, sys, time, urllib.request

ROOT = os.getcwd()
APP = os.path.join(ROOT, "convo-agent")
API = os.environ.get("CONDUCTOR_SERVER_URL", "http://localhost:8080/api").rstrip("/")


def fail(msg):
    print("FAIL: " + msg)
    sys.exit(1)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def launcher(*args, t=240):
    return subprocess.run(["./convo.sh", *args], cwd=APP, capture_output=True, text=True, timeout=t)


def link_of(res):
    sc = res.structuredContent or {}
    text = " ".join(getattr(c, "text", "") for c in res.content)
    return sc, text, bool(sc.get("uiUrl")) or "Execution:" in text


async def session(url):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    out = []
    async with streamablehttp_client(url, timeout=30) as (r, w, _):
        async with ClientSession(r, w) as s:
            await asyncio.wait_for(s.initialize(), 30)
            for msg in ("My name is Jane Doe and my favourite colour is teal.",
                        "What did I just tell you about myself?"):
                res = await asyncio.wait_for(s.call_tool("ask_wealth_advisor", {"message": msg}), 240)
                out.append(res)
    return out


def main():
    if not os.path.exists(os.path.join(APP, "convo.sh")):
        fail("convo-agent/convo.sh does not exist")
    proc = None
    try:
        p = launcher("start", "v4")
        if p.returncode != 0:
            fail("convo.sh start v4 exit %d: %s" % (p.returncode, (p.stderr or p.stdout).strip()[-200:]))
        port = free_port()
        proc = subprocess.Popen([sys.executable, "-m", "v4.mcp_server", "--transport", "http", "--port", str(port)],
                                cwd=APP, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        url = "http://127.0.0.1:%d/mcp" % port
        deadline = time.time() + 60
        while time.time() < deadline:
            if proc.poll() is not None:
                fail("MCP server exited with %s" % proc.returncode)
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=3).read()
                break
            except Exception:
                time.sleep(1)
        else:
            fail("MCP server not healthy within 60s")
        try:
            r1, r2 = asyncio.run(asyncio.wait_for(session(url), 520))
        except BaseException as e:
            fail("MCP session failed: %r" % (e,))
        for i, r in enumerate((r1, r2), 1):
            if r.isError:
                fail("call %d returned isError" % i)
        s1, _, l1 = link_of(r1)
        s2, _, l2 = link_of(r2)
        if not (l1 and l2):
            fail("a result has no execution link")
        sid = s1.get("sessionId")
        if not sid or s2.get("sessionId") != sid:
            fail("sessionId differs: %r vs %r" % (sid, s2.get("sessionId")))
        if s2.get("restored") is not True:
            fail("second call restored=%r" % s2.get("restored"))
        e1, e2 = s1.get("executionId"), s2.get("executionId")
        if not e1 or not e2 or e1 == e2:
            fail("executionIds missing or equal: %r %r" % (e1, e2))
        try:
            with urllib.request.urlopen("%s/workflow/convo_v4_chat_turn/correlated/%s" % (API, sid), timeout=20) as r:
                found = {w.get("workflowId") for w in json.load(r)}
        except Exception as e:
            fail("correlation search failed: %r" % (e,))
        if not {e1, e2} <= found:
            fail("correlation search under %s found %s, missing executions" % (sid, sorted(found)))
        print("OK")
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(10)
            except Exception:
                proc.kill()
        try:
            launcher("stop", "v4", t=60)
        except Exception:
            pass


main()

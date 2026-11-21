import asyncio, os, socket, sys


def fail(msg):
    print("FAIL: " + msg)
    sys.exit(1)


ROOT = os.getcwd()
APP = os.path.join(ROOT, "convo-agent")


def dead_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def text_of(res):
    return " ".join(getattr(c, "text", "") or "" for c in res.content)


async def run(env):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "v4.mcp_server", "--transport", "stdio"],
        env=env, cwd=APP)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await asyncio.wait_for(s.initialize(), 30)
            outs = []
            for name in ("Jane Doe", "John Smith"):
                res = await asyncio.wait_for(
                    s.call_tool("get_portfolio", {"clientName": name}), 60)
                outs.append(res)
            return outs


def main():
    if not os.path.isdir(os.path.join(APP, "v4")):
        fail("convo-agent/v4 does not exist")
    env = dict(os.environ)
    env["CONDUCTOR_SERVER_URL"] = "http://127.0.0.1:%d/api" % dead_port()
    env["PYTHONUNBUFFERED"] = "1"
    try:
        outs = asyncio.run(asyncio.wait_for(run(env), 150))
    except SystemExit:
        raise
    except BaseException as e:
        fail("MCP stdio session failed or server died: %r" % (e,))
    for i, res in enumerate(outs, 1):
        if not res.isError:
            fail("call %d did not return isError (got %r)" % (i, text_of(res)[:120]))
        if "unreachable" not in text_of(res).lower():
            fail("call %d error does not mention 'unreachable': %r" % (i, text_of(res)[:120]))
    print("OK")


main()

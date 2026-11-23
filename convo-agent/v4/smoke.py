"""v4 smoke: talk MCP to the running server like Claude Desktop would.

    python -m v4.smoke [--url http://localhost:8740/mcp]

list_tools has both tools; get_portfolio("Jane Doe") finds holdings; ask_wealth_advisor twice in one
MCP session -> same sessionId, 2nd turn restored. Every executionId is fetched from Conductor and must
be COMPLETED (chat turns with correlationId == sessionId). Exit 0 on success, 1 otherwise.
"""
import argparse
import asyncio
import contextlib
import sys

from common.conductor import Conductor


def is_error(res):
    return bool(getattr(res, "is_error", None) or getattr(res, "isError", None))


def structured(res):
    return getattr(res, "structured_content", None) or getattr(res, "structuredContent", None) or {}


def text(res):
    return " ".join(getattr(c, "text", "") or "" for c in res.content)


@contextlib.asynccontextmanager
async def http_streams(url):
    """(read, write) streams for a Streamable HTTP endpoint on mcp 1.x or 2.x."""
    import mcp.client.streamable_http as m
    if hasattr(m, "streamablehttp_client"):  # mcp 1.x
        async with m.streamablehttp_client(url, timeout=30, sse_read_timeout=600) as s:
            yield s[0], s[1]
        return
    import httpx2  # mcp 2.x
    async with m.create_mcp_http_client(timeout=httpx2.Timeout(30, read=600)) as client:
        async with m.streamable_http_client(url, http_client=client) as s:
            yield s[0], s[1]


async def session(url):
    from mcp import ClientSession
    async with http_streams(url) as (r, w):
        async with ClientSession(r, w) as s:
            await asyncio.wait_for(s.initialize(), 30)
            tools = sorted(t.name for t in (await s.list_tools()).tools)
            port = await asyncio.wait_for(s.call_tool("get_portfolio", {"clientName": "Jane Doe"}), 120)
            turns = []
            for msg in ("Hi, I'm Sam and my favourite colour is teal.", "What is my favourite colour?"):
                turns.append(await asyncio.wait_for(s.call_tool("ask_wealth_advisor", {"message": msg}), 240))
            return tools, port, turns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8740/mcp")
    url = ap.parse_args().url
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + msg)
        ok = ok and bool(cond)

    tools, port, turns = asyncio.run(session(url))
    check({"ask_wealth_advisor", "get_portfolio"} <= set(tools), "tools listed: %s" % tools)
    c = Conductor()
    sp = structured(port)
    check(not is_error(port) and sp.get("found") and "holdings" in str(sp.get("portfolio")),
          "get_portfolio Jane Doe -> %s" % sp.get("uiUrl"))
    if sp.get("executionId"):
        check(c.get_workflow(sp["executionId"]).get("status") == "COMPLETED", "portfolio execution COMPLETED")
    sids = set()
    for i, res in enumerate(turns, 1):
        sc = structured(res)
        check(not is_error(res), "turn %d: %s" % (i, text(res)[:300].replace("\n", " ")))
        sids.add(sc.get("sessionId"))
        if sc.get("executionId"):
            wf = c.get_workflow(sc["executionId"])
            check(wf.get("status") == "COMPLETED" and wf.get("correlationId") == sc.get("sessionId"),
                  "turn %d execution COMPLETED, correlationId=sessionId" % i)
    check(len(sids) == 1 and None not in sids, "same sessionId on both turns: %s" % sids)
    check(structured(turns[1]).get("restored") is True, "turn 2 restored the history")
    print("session view: %s" % c.ui_url(correlation_id=next(iter(sids), "")))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

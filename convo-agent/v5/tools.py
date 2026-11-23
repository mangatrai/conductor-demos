"""The agent's one tool: look up a client's portfolio in v5's own mock data."""
import json
import os

from conductor.ai.agents import tool

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "portfolios.json")


def clients():
    return json.load(open(DATA))["clients"]


@tool
def get_portfolio(client_name: str) -> dict:
    """Look up a client's portfolio (total value, YTD return, holdings) by the client's full name."""
    want = (client_name or "").strip().lower()
    for c in clients():
        if c["name"].lower() == want or want and want in c["name"].lower():
            return c
    return {"error": "no client named %r" % client_name, "knownClients": [c["name"] for c in clients()]}

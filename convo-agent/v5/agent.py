"""The showcase file: the wealth-advisor bot as a Conductor Agent in a few lines of Python."""
from conductor.ai.agents import Agent

from common import config
from v5.tools import get_portfolio

PERSONA = (
    "You are a friendly, concise wealth-advisor assistant helping a financial advisor. "
    "Use the facts from earlier in the conversation. "
    "Only call get_portfolio when the user asks about a named client's portfolio, "
    "then list the holdings by symbol and name. Never invent portfolio data."
)


def build_agent():
    provider, model = config.get("CONVO_LLM_PROVIDER"), config.get("CONVO_LLM_MODEL")
    return Agent(name="wealth_advisor", model=f"{provider}/{model}", instructions=PERSONA,
                 tools=[get_portfolio], max_turns=4, temperature=0.2)

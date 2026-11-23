"""Which LLM path workflows use: native LLM_CHAT_COMPLETE or the convo_llm_chat worker."""
import json
import os

from common import RUN_DIR, config


def effective_mode():
    m = (config.get("CONVO_LLM_MODE") or "auto").strip().lower()
    if m in ("native", "worker"):
        return m
    try:
        m = open(os.path.join(RUN_DIR, "llm_mode")).read().strip()
        if m in ("native", "worker"):
            return m
    except OSError:
        pass
    return "worker"


def checks():
    try:
        return json.load(open(os.path.join(RUN_DIR, "checks.json")))
    except (OSError, ValueError):
        return {}


def get_workflow_ok():
    """True when the native GET_WORKFLOW system task works (Step-0 check); else use the HTTP form."""
    return bool(checks().get("get_workflow", {}).get("ok"))

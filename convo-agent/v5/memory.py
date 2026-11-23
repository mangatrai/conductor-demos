"""Finding the previous turn. The workflow itself loads and checks it (Get Workflow + JQ);
when a front door was not given an execution id it asks Conductor for the session's newest one."""
from common.conductor import ConductorError


def find_prev(conductor, session_id, workflow="convo_v5_agent_turn"):
    """Newest COMPLETED v5 turn for this session (correlationId), or "" (search may lag a second)."""
    try:
        for r in conductor.search_by_correlation(session_id, workflow):
            if r.get("status") == "COMPLETED":
                return r.get("workflowId") or ""
    except ConductorError:
        pass
    return ""

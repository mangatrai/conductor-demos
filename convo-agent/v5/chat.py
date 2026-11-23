"""python -m v5.chat --session S [--prev ID] "message"   -> prints the turn as JSON
python -m v5.chat --session S --interactive             -> REPL (/quit ends it)
"""
import argparse
import json
import sys
import uuid

from v5.turn import TurnError, run_turn

KEYS = ("reply", "restored", "memorySource", "memoryNote", "agentMode", "toolCalls",
        "executionId", "sessionId", "uiUrl", "history")


def turn(session, message, prev=""):
    out = run_turn(session, message, prev)
    return {k: out.get(k) for k in KEYS}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Chat with the v5 wealth_advisor Conductor Agent")
    ap.add_argument("--session", default="")
    ap.add_argument("--prev", default="", help="previous executionId (default: the session's newest turn)")
    ap.add_argument("--interactive", "-i", action="store_true")
    ap.add_argument("message", nargs="*")
    a = ap.parse_args(argv)
    session = a.session or "v5-" + uuid.uuid4().hex[:8]
    try:
        if not a.interactive:
            if not a.message:
                ap.error("give a message, or --interactive")
            print(json.dumps(turn(session, " ".join(a.message), a.prev), indent=2))
            return 0
        print("session %s - type /quit to end" % session)
        prev = a.prev
        for line in sys.stdin:
            line = line.strip()
            if line in ("/quit", "/exit"):
                break
            if line:
                out = turn(session, line, prev)
                prev = out["executionId"]
                print("advisor> %s\n  [%s memory=%s tools=%s %s]" % (out["reply"], out["agentMode"], out["memorySource"],
                                                                     [t.get("name") for t in out["toolCalls"] or []], out["uiUrl"]))
        return 0
    except (TurnError, Exception) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

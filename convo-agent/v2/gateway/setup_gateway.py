"""Create (or update) the `wealth-advisor` service on the Orkes API Gateway.

    python -m v2.gateway.setup_gateway [--dry-run]

On Conductor OSS (or with --dry-run) it only prints the service definition: the API Gateway is an
Orkes feature, and `python -m v2.server` on :8720 is the local stand-in with the same routes.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NOTICE = "API Gateway is Orkes-only; the local front door on :8720 is the stand-in (python -m v2.server)."


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the definition, change nothing")
    a = ap.parse_args(argv)
    service = json.load(open(os.path.join(HERE, "wealth_advisor_service.json")))

    from common import config
    flavor = config.get("CONDUCTOR_FLAVOR", "") or ("orkes" if config.get("CONDUCTOR_AUTH_KEY", "") else "oss")
    if a.dry_run or flavor != "orkes":
        print(json.dumps(service, indent=2))
        for r in service["routes"]:
            print("route %-4s /%s%s -> %s (sync)" % (r["method"], service["name"], r["path"], r["workflowName"]))
        print(NOTICE)
        return 0

    from common.conductor import Conductor, ConductorError
    c = Conductor()
    # Verify: gateway REST path on your Orkes cluster (see gateway/README.md).
    path = "/gateway/config/service"
    try:
        try:
            c._req("PUT", "%s/%s" % (path, service["name"]), json=service)
        except ConductorError as e:
            if e.status != 404:
                raise
            c._req("POST", path, json=service)
    except ConductorError as e:
        print("gateway setup failed: %s" % e)
        return 1
    base = c.base[:-4] if c.base.endswith("/api") else c.base
    print("wealth-advisor service ready: %s/gateway/%s  (routes /chat, /session)" % (base, service["name"]))
    print("Put {\"apiBase\": \"<that url>\", \"apiKey\": \"<key>\"} in v2/web/config.local.json to point the page at it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

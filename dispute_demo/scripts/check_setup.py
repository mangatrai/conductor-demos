"""Pre-flight check: .env values present, server reachable, key valid (Orkes). Run by start.sh.

    python scripts/check_setup.py
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.orkes import OrkesError, client, flavor  # noqa: E402  (importing loads .env)

OSS_TESTED = (3, 34)  # oldest Conductor OSS release this demo has been tested on


def fail(msg: str) -> None:
    print(f"\n  ✗ {msg}\n")
    sys.exit(1)


def unreachable(url: str, e: Exception) -> None:
    hint = ""
    if "/token" in str(e) and "404" in str(e):
        hint = ("\n    This server has no login endpoint, so it looks like Conductor OSS: set CONDUCTOR_FLAVOR=oss.")
    in_container = Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()
    if in_container and any(h in url for h in ("localhost", "127.0.0.1")):
        hint = ("\n    Inside a container, localhost is the container itself. Use the Conductor host's name or IP,\n"
                "    or http://host.docker.internal:8080/api (Podman: host.containers.internal) for a server on this machine.")
    fail(f"Cannot reach {url}: {e}{hint}")


def main() -> None:
    oss = flavor() == "oss"
    required = ["CONDUCTOR_SERVER_URL"] + ([] if oss else ["CONDUCTOR_AUTH_KEY", "CONDUCTOR_AUTH_SECRET"])
    missing = [k for k in required if not os.environ.get(k) or "<" in os.environ[k]]
    if missing:
        fail(f"Missing: {', '.join(missing)}\n"
             f"    Copy .env.example to .env at the repository root and fill in your Conductor\n"
             f"    server URL (and, for Orkes, the access key). In a container, pass them with --env-file or -e.")
    url = os.environ["CONDUCTOR_SERVER_URL"].rstrip("/")
    if not url.endswith("/api"):
        fail(f"CONDUCTOR_SERVER_URL should end with /api (got {url})")
    if oss:
        check_oss(url)
        return
    try:
        o = client()
        version = o.call("GET", "/version", raw=True).strip('"')
        o.call("GET", "/metadata/taskdefs", params={"access": "READ"})
    except OrkesError as e:
        fail(f"Orkes rejected the request ({e}).\n"
             f"    Check the key id/secret, and that the application has the Worker, Metadata API and\n"
             f"    Business Rule Manager roles.")
    except Exception as e:  # network, DNS, TLS
        unreachable(url, e)
    print(f"  ✓ Connected to Orkes {version} at {url}")
    major_minor = tuple(int(x) for x in version.split(".")[:2] if x.isdigit())
    if major_minor < (5, 6):
        fail(f"Orkes {version} is too old: triage uses a decision rule saved in Orkes (needs 5.6 or later).")
    try:  # 404 = rule not created yet (fine, register.py creates it); 403 = the key can't manage decision rules
        o.call("GET", "/business-rules/dispute_triage_rules")
    except OrkesError as e:
        if e.status == 403:
            fail("The access key can't manage decision rules (403 on /api/business-rules).\n"
                 "    In Orkes: Access Control > Applications > your app > add the 'Business Rule Manager' role.")
        if e.status != 404:
            raise
    print("  ✓ Decision rules: the key can create and update them")


def check_oss(url: str) -> None:
    try:
        o = client()
        version = o.call("GET", "/version", raw=True).strip('"')
        o.call("GET", "/metadata/taskdefs")
    except OrkesError as e:
        fail(f"Conductor rejected the request ({e}).\n"
             f"    If this is an Orkes cluster, set CONDUCTOR_FLAVOR=orkes and the access key.")
    except Exception as e:  # network, DNS, TLS
        unreachable(url, e)
    print(f"  ✓ Connected to Conductor OSS {version} at {url}")
    major_minor = tuple(int(x) for x in version.split(".")[:2] if x.isdigit())
    if major_minor < OSS_TESTED:
        print(f"  ! Conductor OSS {version} is older than {'.'.join(map(str, OSS_TESTED))}, "
              f"the oldest release this demo was tested on. It may still work.")
    print("  ✓ OSS mode: triage runs as an INLINE task from rules/dispute_rules.csv; "
          "analyst and ops decisions are made in the console")


if __name__ == "__main__":
    main()

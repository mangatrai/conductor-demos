"""Pre-flight check: .env values present, cluster reachable, key valid. Run by start.sh.

    python scripts/check_setup.py
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.orkes import _ENV_FILE, OrkesError, client  # noqa: E402  (importing loads .env)

REQUIRED = ["CONDUCTOR_SERVER_URL", "CONDUCTOR_AUTH_KEY", "CONDUCTOR_AUTH_SECRET"]


def fail(msg: str) -> None:
    print(f"\n  ✗ {msg}\n")
    sys.exit(1)


def main() -> None:
    missing = [k for k in REQUIRED if not os.environ.get(k) or "<" in os.environ[k]]
    if missing:
        fail(f"Missing in {_ENV_FILE}: {', '.join(missing)}\n"
             f"    Copy .env.example to .env at the repository root and fill in your Orkes cluster URL and access key.")
    url = os.environ["CONDUCTOR_SERVER_URL"].rstrip("/")
    if not url.endswith("/api"):
        fail(f"CONDUCTOR_SERVER_URL should end with /api (got {url})")
    try:
        o = client()
        version = o.call("GET", "/version", raw=True).strip('"')
        o.call("GET", "/metadata/taskdefs", params={"access": "READ"})
    except OrkesError as e:
        fail(f"Orkes rejected the request ({e}).\n"
             f"    Check the key id/secret, and that the application has the Worker, Metadata API and\n"
             f"    Business Rule Manager roles.")
    except Exception as e:  # network, DNS, TLS
        fail(f"Cannot reach {url}: {e}")
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


if __name__ == "__main__":
    main()

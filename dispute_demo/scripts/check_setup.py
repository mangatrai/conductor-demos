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
             f"    Check the key id/secret, and that the application has the Worker and Metadata API roles.")
    except Exception as e:  # network, DNS, TLS
        fail(f"Cannot reach {url}: {e}")
    print(f"  ✓ Connected to Orkes {version} at {url}")
    rules = os.environ.get("DISPUTE_RULES_URL", "").strip()
    print(f"  ✓ Triage rules: {'BUSINESS_RULE from ' + rules if rules else 'INLINE fallback (DISPUTE_RULES_URL not set)'}")


if __name__ == "__main__":
    main()

"""S6: discover version manifests and resolve the versions a command names."""
import glob
import json
import os

from common import APP_DIR


class UnknownVersion(Exception):
    pass


def discover():
    out = []
    for f in sorted(glob.glob(os.path.join(APP_DIR, "v*", "manifest.json")),
                    key=lambda p: int("".join(c for c in os.path.basename(os.path.dirname(p)) if c.isdigit()) or 0)):
        try:
            out.append(json.load(open(f)))
        except ValueError:
            continue
    return out


def select(args):
    known = discover()
    names = [m["version"] for m in known]
    if not args or "all" in args:
        return known
    for a in args:
        if a not in names:
            raise UnknownVersion("unknown version: %s (known: %s)" % (a, " ".join(names)))
    return [m for m in known if m["version"] in args]

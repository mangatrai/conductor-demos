"""Hub: `python -m hub.server --port 8700` (run from convo-agent/).

GET /              the page (hub/static/index.html)
GET /api/versions  one entry per vN/manifest.json, with a live health probe per process
GET /api/platform  Conductor flavor, LLM mode, model, Ollama, Step-0 checks

Read-only: it never starts or stops anything; the page shows the ./convo.sh commands to copy.
"""
import argparse
import json
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from common import RUN_DIR, config, manifests

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def probe(url, timeout=0.5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status < 500
    except Exception:  # connection refused, timeout, HTTP error: not healthy
        return False


def versions():
    out = []
    for m in manifests.discover():
        procs = m.get("processes", [])
        with ThreadPoolExecutor(max_workers=max(1, len(procs))) as pool:
            health = list(pool.map(lambda p: probe("http://127.0.0.1:%s%s" % (p.get("port"), p.get("health", "/"))),
                                   procs))
        entry = {
            "version": m["version"],
            "title": m.get("title", m["version"]),
            "summary": m.get("summary", ""),
            "features": m.get("features", []),
            "links": m.get("links", []),
            "processes": [{"name": p["name"], "port": p.get("port"), "healthy": h} for p, h in zip(procs, health)],
            "running": bool(procs) and all(health),
        }
        if not procs:  # CLI-only version (v1)
            entry["cli"] = "python -m %s.chat" % m["version"]
        out.append(entry)
    return out


def _read(path):
    try:
        return open(path).read().strip()
    except OSError:
        return None


def platform():
    try:
        checks = json.loads(_read(os.path.join(RUN_DIR, "checks.json")) or "null")
    except ValueError:
        checks = None
    ollama = config.get("OLLAMA_URL").rstrip("/")
    return {
        "flavor": config.get("CONDUCTOR_FLAVOR", "") or ("orkes" if config.get("CONDUCTOR_AUTH_KEY", "") else "oss"),
        "conductor_url": config.get("CONDUCTOR_SERVER_URL"),
        "llm_mode": _read(os.path.join(RUN_DIR, "llm_mode")) or config.get("CONVO_LLM_MODE"),
        "model": config.get("CONVO_LLM_MODEL"),
        "ollama_up": probe(ollama + "/api/tags"),
        "checks": checks,
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/versions":
            return self._send(200, json.dumps(versions()), "application/json")
        if path == "/api/platform":
            return self._send(200, json.dumps(platform()), "application/json")
        if path in ("/", "/index.html"):
            with open(os.path.join(STATIC, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        self._send(404, json.dumps({"error": "not found"}), "application/json")

    def log_message(self, *args):  # keep the log quiet
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8700)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print("hub -> http://localhost:%d/" % args.port, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

"""Mock portfolio API for v4 (own snapshot copy; versions never import each other) (stdlib only).

    python -m v4.mock_api --port 8741 [--fail]

GET /healthz            -> {"status": "ok"}
GET /clients            -> {"clients": [names...]}
GET /portfolio?name=X   (or /portfolio/X) -> 200 {found: true, client, totalValue, ...}
                           200 {found: false, name, known: [...]}   (unknown client)
                           503 {error: ...}                          (with --fail)
"""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "portfolios.json")
FAIL = False


def load():
    with open(DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


def norm(text):
    return " ".join((text or "").lower().split())


def find_client(data, name):
    """Case/space-insensitive match on full name, or on a unique last name."""
    key = norm(name)
    if not key:
        return None
    clients = data["clients"]
    for c in clients:
        if norm(c["name"]) == key:
            return c
    last = [c for c in clients if norm(c["name"]).split()[-1] == key]
    return last[0] if len(last) == 1 else None


def portfolio_body(data, name):
    c = find_client(data, name)
    if c is None:
        return {"found": False, "name": name, "known": [x["name"] for x in data["clients"]]}
    return {
        "found": True,
        "client": {"name": c["name"], "riskProfile": c["riskProfile"], "advisor": c["advisor"]},
        "totalValue": c["totalValue"],
        "currency": data["currency"],
        "asOf": data["asOf"],
        "holdings": c["holdings"],
        "ytdReturnPct": c["ytdReturnPct"],
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        url = urlparse(self.path)
        data = load()
        if url.path == "/healthz":
            self._send(200, {"status": "ok"})
        elif url.path == "/clients":
            self._send(200, {"clients": [c["name"] for c in data["clients"]]})
        elif url.path == "/portfolio" or url.path.startswith("/portfolio/"):
            if FAIL:
                self._send(503, {"error": "portfolio service unavailable"})
                return
            # /portfolio?name=Jane%20Doe  or  /portfolio/Jane%20Doe
            name = unquote(url.path[len("/portfolio/"):]) if url.path.startswith("/portfolio/") \
                else (parse_qs(url.query).get("name") or [""])[0]
            name = unquote(name)  # tolerate a double-encoded name
            self._send(200, portfolio_body(data, name))
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        pass


def main():
    global FAIL
    ap = argparse.ArgumentParser(description="v4 mock portfolio API")
    ap.add_argument("--port", type=int, default=8741)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--fail", action="store_true", help="return 503 for /portfolio (API-down demo)")
    args = ap.parse_args()
    FAIL = args.fail
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print("mock portfolio API on http://%s:%d%s" % (args.host, args.port, " (--fail)" if FAIL else ""), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

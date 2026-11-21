"""Config: real env > convo-agent/.env > repo .env (first file wins, real env always wins)."""
import os

from common import APP_DIR, REPO_DIR

DEFAULTS = {
    "CONDUCTOR_SERVER_URL": "http://localhost:8080/api",
    "CONVO_LLM_PROVIDER": "ollama",
    "CONVO_LLM_MODEL": "qwen2.5:3b",
    "CONVO_LLM_MODE": "auto",
    "OLLAMA_URL": "http://localhost:11434",
}
_loaded = False


def _parse(path):
    out = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                if k.startswith("export "):
                    k = k[7:].strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                    v = v[1:-1]
                out[k] = v
    except OSError:
        pass
    return out


def load(files=None):
    """Load .env files into os.environ without overriding values already set."""
    global _loaded
    if files is None:
        files = [os.path.join(APP_DIR, ".env"), os.path.join(REPO_DIR, ".env")]
    for path in files:
        for k, v in _parse(path).items():
            os.environ.setdefault(k, v)
    _loaded = True


def get(key, default=None):
    if not _loaded:
        load()
    v = os.environ.get(key)
    if v in (None, ""):
        return DEFAULTS.get(key, default) if default is None else default
    return v

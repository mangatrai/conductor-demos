"""Ollama lifecycle: start `ollama serve` when it is installed and not running; stop only what we started."""
import os
import shutil
import signal
import subprocess
import time

import requests

from common import RUN_DIR, config


def _url():
    return config.get("OLLAMA_URL").rstrip("/")


def tags():
    try:
        r = requests.get(_url() + "/api/tags", timeout=3)
        r.raise_for_status()
        return [m.get("name") for m in r.json().get("models", [])]
    except (requests.RequestException, ValueError):
        return None


def ensure_running(wait=30):
    if tags() is not None:
        return True
    exe = shutil.which("ollama")
    if not exe:
        return False
    try:  # detached, so it outlives this command and never holds our pipes
        proc = subprocess.Popen([exe, "serve"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return False
    os.makedirs(RUN_DIR, exist_ok=True)
    open(os.path.join(RUN_DIR, "ollama.started"), "w").write(str(proc.pid))
    deadline = time.time() + wait
    while time.time() < deadline:
        if tags() is not None:
            return True
        time.sleep(0.5)
    return False


def ensure_model(model=None):
    model = model or config.get("CONVO_LLM_MODEL")
    have = tags() or []
    if model in have or (":" not in model and model + ":latest" in have):
        return True
    try:
        r = requests.post(_url() + "/api/pull", json={"name": model, "stream": False}, timeout=1800)
        return r.status_code < 300
    except requests.RequestException:
        return False


def stop():
    """Stop Ollama only if ensure_running() started it (its pid is in .run/ollama.started)."""
    marker = os.path.join(RUN_DIR, "ollama.started")
    if not os.path.exists(marker):
        return False
    try:
        os.kill(int(open(marker).read().strip()), signal.SIGTERM)
    except (ValueError, OSError):
        pass
    os.remove(marker)
    return True

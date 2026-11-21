"""Ollama lifecycle via the machine's help-scripts."""
import os
import subprocess
import time

import requests

from common import RUN_DIR, config

SCRIPTS = "/Users/mrai/sandbox/castles/help-scripts"


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
    script = os.path.join(SCRIPTS, "start_ollama.sh")
    if not os.path.exists(script):
        return False
    try:  # detached: the script backgrounds `ollama serve`, never let it hold our pipes
        subprocess.Popen(["bash", script], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True).wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass
    os.makedirs(RUN_DIR, exist_ok=True)
    open(os.path.join(RUN_DIR, "ollama.started"), "w").write(str(time.time()))
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
    marker = os.path.join(RUN_DIR, "ollama.started")
    if not os.path.exists(marker):
        return False
    script = os.path.join(SCRIPTS, "stop_ollama.sh")
    if os.path.exists(script):
        try:
            subprocess.run(["bash", script], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=30)
        except subprocess.TimeoutExpired:
            pass
    os.remove(marker)
    return True

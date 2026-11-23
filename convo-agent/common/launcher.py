"""./convo.sh {setup|start|stop|status|smoke|list|checks} [v1 v2 ...|all]"""
import os
import shutil
import signal
import subprocess
import sys
import time

import requests

from common import APP_DIR, RUN_DIR, checks, llm_mode, manifests, ollama, register
from common.conductor import ConductorError

HUB = {"name": "hub", "cmd": ["python", "-m", "hub.server", "--port", "8700"], "port": 8700, "health": "/api/versions"}
WORKER = {"name": "llm_worker", "cmd": ["python", "-m", "common.llm_worker"]}


def _env():
    env = dict(os.environ)
    env["PYTHONPATH"] = APP_DIR + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def _cmd(cmd):
    return [sys.executable if c == "python" else c for c in cmd]


def _pidfile(group, name, create=False):
    d = os.path.join(RUN_DIR, group) if group else RUN_DIR
    if create:
        os.makedirs(d, exist_ok=True)
    return os.path.join(d, name + ".pid"), os.path.join(d, name + ".log")


def _pid(group, name):
    try:
        pid = int(open(_pidfile(group, name)[0]).read().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def _healthy(proc, timeout=0.5):
    if not proc.get("port"):
        return None
    try:
        return requests.get("http://localhost:%s%s" % (proc["port"], proc.get("health", "/")), timeout=timeout).status_code < 500
    except requests.RequestException:
        return False


def _spawn(group, proc):
    pid = _pid(group, proc["name"])
    if pid and _healthy(proc) is not False:
        return pid
    pf, lf = _pidfile(group, proc["name"], create=True)
    p = subprocess.Popen(_cmd(proc["cmd"]), cwd=APP_DIR, env=_env(), stdout=open(lf, "a"), stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    open(pf, "w").write(str(p.pid))
    if proc.get("port"):
        deadline = time.time() + 20
        while time.time() < deadline and p.poll() is None and not _healthy(proc):
            time.sleep(0.3)
        if not _healthy(proc):
            print("  ! %s/%s not healthy on port %s (see %s)" % (group or "-", proc["name"], proc["port"], lf))
    return p.pid


def _kill(group, name):
    pid = _pid(group, name)
    pf = _pidfile(group, name)[0]
    if pid:
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            pass
        for _ in range(50):
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
            except OSError:
                break
        else:
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
    if os.path.exists(pf):
        os.remove(pf)
    return pid


def cmd_list(sel):
    for m in sel:
        print("%s  %s" % (m["version"], m.get("title", "")))
        if m.get("summary"):
            print("    %s" % m["summary"])
        print("    features: %s" % ", ".join(m.get("features", [])))
    return 0


def cmd_status(sel):
    print("%-8s %-12s %-8s %-6s %s" % ("version", "process", "pid", "port", "healthy"))
    rows = [("platform", None, WORKER), ("platform", None, HUB)] + \
           [(m["version"], m["version"], p) for m in sel for p in m.get("processes", [])]
    for label, group, p in rows:
        h = _healthy(p) if _pid(group, p["name"]) else False
        print("%-8s %-12s %-8s %-6s %s" % (label, p["name"], _pid(group, p["name"]) or "-", p.get("port", "-"),
                                          "-" if h is None else ("yes" if h else "no")))
    for m in sel:
        if not m.get("processes"):
            print("%-8s %-12s %-8s %-6s %s" % (m["version"], "(workflow only)", "-", "-", "-"))
    return 0


def cmd_start(sel):
    if not ollama.ensure_running():
        print("  ! Ollama is not reachable; LLM turns will fail until it runs")
    else:
        ollama.ensure_model()
    if not os.path.exists(os.path.join(RUN_DIR, "llm_mode")):
        if checks.run_checks(start_ollama=False) != 0:
            return 1
    try:
        register.register_common()
        for m in sel:
            names = register.register_version(m["version"])
            print("registered %s: %s" % (m["version"], ", ".join(names) or "(nothing)"))
    except ConductorError as e:
        print("Conductor error: %s" % e, file=sys.stderr)
        return 1
    if llm_mode.effective_mode() == "worker":
        _spawn(None, WORKER)
    for m in sel:
        for p in m.get("processes", []):
            _spawn(m["version"], p)
            print("started %s/%s -> http://localhost:%s/" % (m["version"], p["name"], p.get("port")))
    if os.path.exists(os.path.join(APP_DIR, "hub", "server.py")):
        _spawn(None, HUB)
        print("hub -> http://localhost:8700/")
    return 0


def cmd_stop(sel, everything):
    for m in sel:
        for p in m.get("processes", []):
            if _kill(m["version"], p["name"]):
                print("stopped %s/%s" % (m["version"], p["name"]))
    if everything:
        for p in (WORKER, HUB):
            if _kill(None, p["name"]):
                print("stopped %s" % p["name"])
        if ollama.stop():
            print("stopped ollama")
    return 0


def cmd_smoke(sel):
    bad = []
    for m in sel:
        if not m.get("smoke"):
            continue
        print("== smoke %s" % m["version"], flush=True)
        r = subprocess.run(_cmd(m["smoke"]), cwd=APP_DIR, env=_env(), stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            bad.append(m["version"])
    print("smoke failed: %s" % " ".join(bad) if bad else "smoke ok")
    return 1 if bad else 0


def cmd_setup(sel):
    # convo.sh setup has already installed requirements.txt into this Python (this module imports them).
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], cwd=APP_DIR, capture_output=True)
    env, example = os.path.join(APP_DIR, ".env"), os.path.join(APP_DIR, ".env.example")
    if not os.path.exists(env) and os.path.exists(example):
        shutil.copy(example, env)
    if ollama.ensure_running():
        ollama.ensure_model()
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    cmd, args = argv[0], argv[1:]
    if cmd == "checks":
        return checks.run_checks()
    try:
        sel = manifests.select(args)
    except manifests.UnknownVersion as e:
        print(str(e), file=sys.stderr)
        return 2
    everything = not args or "all" in args
    if cmd == "list":
        return cmd_list(sel)
    if cmd == "status":
        return cmd_status(sel)
    if cmd == "start":
        return cmd_start(sel)
    if cmd == "stop":
        return cmd_stop(sel, everything)
    if cmd == "smoke":
        return cmd_smoke(sel)
    if cmd == "setup":
        return cmd_setup(sel)
    print("unknown command: %s" % cmd, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

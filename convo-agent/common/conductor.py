"""S1: a tiny Conductor REST client (OSS and Orkes) built on requests."""
import time

import requests

from common import config

TERMINAL = {"COMPLETED", "FAILED", "TERMINATED", "TIMED_OUT"}


class ConductorError(RuntimeError):
    def __init__(self, status, path, body):
        super().__init__("Conductor %s %s: %s" % (status, path, (body or "")[:300]))
        self.status, self.path, self.body = status, path, body


class Conductor:
    def __init__(self):
        self.base = config.get("CONDUCTOR_SERVER_URL").rstrip("/")
        self.key = config.get("CONDUCTOR_AUTH_KEY", "")
        self.secret = config.get("CONDUCTOR_AUTH_SECRET", "")
        self.flavor = config.get("CONDUCTOR_FLAVOR", "") or ("orkes" if self.key else "oss")
        self._token = None

    # ---- transport
    def _auth(self, refresh=False):
        if self.flavor != "orkes" or not self.key:
            return {}
        if refresh or not self._token:
            r = requests.post(self.base + "/token", json={"keyId": self.key, "keySecret": self.secret}, timeout=15)
            if r.status_code >= 300:
                raise ConductorError(r.status_code, "/token", r.text)
            self._token = r.json()["token"]
        return {"X-Authorization": self._token}

    def _req(self, method, path, **kw):
        kw.setdefault("timeout", 30)
        for attempt in (0, 1):
            try:
                r = requests.request(method, self.base + path, headers=self._auth(refresh=attempt == 1), **kw)
            except requests.RequestException as e:
                raise ConductorError(0, path, str(e))
            if r.status_code == 401 and attempt == 0 and self.flavor == "orkes":
                continue
            if r.status_code >= 300:
                raise ConductorError(r.status_code, path, r.text)
            if not r.content:
                return None
            try:
                return r.json()
            except ValueError:
                return r.text
        return None

    # ---- metadata
    def register_task_defs(self, defs):
        if not defs:
            return
        try:
            self._req("POST", "/metadata/taskdefs", json=defs)
        except ConductorError:
            for d in defs:  # already exists -> update each
                self._req("PUT", "/metadata/taskdefs", json=d)

    def register_workflow(self, wf):
        self._req("PUT", "/metadata/workflow", json=[wf])

    # ---- executions
    def start_workflow(self, name, input, correlation_id=None):
        body = {"name": name, "version": 1, "input": input or {}}
        if correlation_id:
            body["correlationId"] = correlation_id
        out = self._req("POST", "/workflow", json=body)
        return out if isinstance(out, str) else str(out)

    def run_sync(self, name, input, correlation_id=None, wait_seconds=30):
        wid = self.start_workflow(name, input, correlation_id)
        deadline = time.time() + wait_seconds
        while True:
            wf = self.get_workflow(wid)
            if wf.get("status") in TERMINAL or time.time() >= deadline:
                wf.setdefault("workflowId", wid)
                return wf
            time.sleep(0.25)

    def get_workflow(self, workflow_id, include_tasks=False):
        return self._req("GET", "/workflow/%s" % workflow_id,
                         params={"includeTasks": "true" if include_tasks else "false"})

    def terminate(self, workflow_id, reason="terminated by convo-agent"):
        try:
            self._req("DELETE", "/workflow/%s" % workflow_id, params={"reason": reason})
        except ConductorError:
            pass

    def search_by_correlation(self, correlation_id, workflow_name=None, size=50):
        q = "correlationId='%s'" % correlation_id
        if workflow_name:
            q += " AND workflowType='%s'" % workflow_name
        out = self._req("GET", "/workflow/search", params={"query": q, "size": size, "sort": "startTime:DESC"})
        res = (out or {}).get("results", []) if isinstance(out, dict) else []
        return sorted(res, key=lambda r: r.get("startTime") or 0, reverse=True)

    def ui_url(self, workflow_id=None, correlation_id=None):
        ui = config.get("CONDUCTOR_UI_URL", "")
        if not ui:
            ui = self.base[:-4] if self.base.endswith("/api") else self.base
            if self.flavor == "oss" and ui.endswith(":8080"):
                ui = ui[:-5] + ":5000"
        ui = ui.rstrip("/")
        if workflow_id:
            return "%s/execution/%s" % (ui, workflow_id)
        if correlation_id:
            return "%s/search?correlationId=%s" % (ui, correlation_id)
        return ui

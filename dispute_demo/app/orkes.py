"""Thin REST client for Conductor: Orkes Conductor or Conductor OSS.

The Python SDK (2.0.0) has no human-task client, so the demo talks to the REST API
directly for everything. Settings come from the same env vars the SDK uses:
CONDUCTOR_SERVER_URL, CONDUCTOR_AUTH_KEY, CONDUCTOR_AUTH_SECRET, plus:

  CONDUCTOR_FLAVOR  "orkes" or "oss". If unset: orkes when an auth key is set, otherwise oss.
  CONDUCTOR_UI_URL  optional; the UI address when it is not the server URL minus /api.

On OSS there is no login, no Human Task API, no user forms and no decision rules. The demo
keeps the same workflows and swaps only those pieces (see scripts/register.py and
complete_human_task below).
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import requests

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def load_env() -> None:
    """Load KEY=VALUE lines from the workspace .env without overriding real env vars."""
    if not _ENV_FILE.exists():
        return
    for line in _ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()


def flavor() -> str:
    f = os.environ.get("CONDUCTOR_FLAVOR", "").strip().lower()
    if not f:
        return "orkes" if os.environ.get("CONDUCTOR_AUTH_KEY") else "oss"
    if f not in ("orkes", "oss"):
        raise SystemExit(f"CONDUCTOR_FLAVOR must be 'orkes' or 'oss', not '{f}'")
    return f


class OrkesError(RuntimeError):
    def __init__(self, status: int, path: str, body: str):
        super().__init__(f"{status} on {path}: {body[:400]}")
        self.status = status
        self.body = body


class Orkes:
    def __init__(self) -> None:
        self.base = os.environ["CONDUCTOR_SERVER_URL"].rstrip("/")
        self.flavor = flavor()
        self.is_oss = self.flavor == "oss"
        self._key = os.environ.get("CONDUCTOR_AUTH_KEY", "")
        self._secret = os.environ.get("CONDUCTOR_AUTH_SECRET", "")
        if not self.is_oss and not (self._key and self._secret):
            raise SystemExit("Orkes needs CONDUCTOR_AUTH_KEY and CONDUCTOR_AUTH_SECRET "
                             "(or set CONDUCTOR_FLAVOR=oss for Conductor OSS)")
        self._token: str | None = None
        self._token_at = 0.0
        self._lock = threading.Lock()
        self.session = requests.Session()

    # -- auth -------------------------------------------------------------
    def _auth(self) -> str:
        with self._lock:
            if not self._token or time.time() - self._token_at > 30 * 60:
                r = self.session.post(
                    f"{self.base}/token",
                    json={"keyId": self._key, "keySecret": self._secret},
                    timeout=15,
                )
                r.raise_for_status()
                self._token = r.json()["token"]
                self._token_at = time.time()
            return self._token

    def call(self, method: str, path: str, *, json=None, params=None, raw: bool = False):
        for attempt in range(2):
            r = self.session.request(
                method,
                f"{self.base}{path}",
                json=json,
                params=params,
                headers={} if self.is_oss else {"X-Authorization": self._auth()},
                timeout=30,
            )
            if r.status_code == 401 and attempt == 0 and not self.is_oss:
                self._token = None  # expired token, refresh once
                continue
            break
        if r.status_code >= 400:
            raise OrkesError(r.status_code, path, r.text)
        if raw:
            return r.text
        if not r.text:
            return None
        try:
            return r.json()
        except ValueError:
            return r.text

    @property
    def ui_base(self) -> str:
        if os.environ.get("CONDUCTOR_UI_URL"):
            return os.environ["CONDUCTOR_UI_URL"].rstrip("/")
        return self.base[: -len("/api")] if self.base.endswith("/api") else self.base

    # -- metadata ---------------------------------------------------------
    def register_task_defs(self, defs: list[dict]):
        return self.call("POST", "/metadata/taskdefs", json=defs)

    def update_task_defs(self, defs: list[dict]):
        for d in defs:
            self.call("PUT", "/metadata/taskdefs", json=d)

    def upsert_workflow_defs(self, defs: list[dict]):
        return self.call("PUT", "/metadata/workflow", json=defs)

    def save_user_form(self, form: dict):
        return self.call("POST", "/human/template", json=form, params={"newVersion": "false"})

    # -- workflows --------------------------------------------------------
    def start_workflow(self, name: str, input: dict, *, version: int | None = None,
                       correlation_id: str | None = None) -> str:
        body = {"name": name, "input": input}
        if version is not None:
            body["version"] = version
        if correlation_id:
            body["correlationId"] = correlation_id
        return self.call("POST", "/workflow", json=body, raw=True).strip('"')

    def get_workflow(self, workflow_id: str, include_tasks: bool = True) -> dict:
        return self.call("GET", f"/workflow/{workflow_id}",
                         params={"includeTasks": str(include_tasks).lower()})

    def search_workflows(self, *, query: str | None = None, free_text: str = "*",
                         size: int = 50, sort: str = "startTime:DESC") -> dict:
        params = {"start": 0, "size": size, "freeText": free_text, "sort": sort}
        if query:
            params["query"] = query
        return self.call("GET", "/workflow/search", params=params)

    def terminate_workflow(self, workflow_id: str, reason: str = "demo reset"):
        return self.call("DELETE", f"/workflow/{workflow_id}", params={"reason": reason})

    # -- tasks ------------------------------------------------------------
    def complete_task_by_ref(self, workflow_id: str, task_ref: str, output: dict,
                             status: str = "COMPLETED"):
        return self.call("POST", f"/tasks/{workflow_id}/{task_ref}/{status}", json=output)

    # -- human tasks ------------------------------------------------------
    def search_human_tasks(self, **filters) -> dict:
        body = {"searchType": "ADMIN", "start": 0, "size": 100}
        body.update(filters)
        return self.call("POST", "/human/tasks/search", json=body)

    def get_human_task(self, task_id: str) -> dict:
        return self.call("GET", f"/human/tasks/{task_id}", params={"withTemplate": "true"})

    def claim_human_task_external(self, task_id: str, user_id: str) -> dict:
        return self.call("POST", f"/human/tasks/{task_id}/externalUser/{user_id}",
                         params={"overrideAssignment": "true"})

    def complete_human_task(self, workflow_id: str, task_id: str, user_id: str, output: dict):
        """Complete a HUMAN task as user_id.

        Orkes: claim it, then complete it through the Human Task API, which also checks the output
        against the task's user form. OSS: a HUMAN task is a plain wait, so complete it with the
        standard task update (by task id, so the right DO_WHILE iteration is completed)."""
        if self.is_oss:
            return self.call("POST", "/tasks", json={
                "workflowInstanceId": workflow_id, "taskId": task_id,
                "status": "COMPLETED", "outputData": output})
        self.claim_human_task_external(task_id, user_id)
        return self.call("POST", f"/human/tasks/{task_id}/update", json=output,
                         params={"complete": "true"})


_client: Orkes | None = None


def client() -> Orkes:
    global _client
    if _client is None:
        _client = Orkes()
    return _client

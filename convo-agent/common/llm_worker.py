"""S3: convo_llm_chat worker. chat() is the pure call; `python -m common.llm_worker` polls Conductor."""
import json
import socket
import sys
import threading
import time

import requests

from common import config

TASK = "convo_llm_chat"


def chat(input):
    """Call Ollama /api/chat with the native LLM task's inputParameters; return {"result": ...}."""
    url = config.get("OLLAMA_URL").rstrip("/") + "/api/chat"
    msgs = [{"role": m.get("role", "user"), "content": m.get("message", m.get("content", ""))}
            for m in input.get("messages") or []]
    body = {"model": input.get("model") or config.get("CONVO_LLM_MODEL"), "messages": msgs, "stream": False,
            "options": {"temperature": input.get("temperature", 0.2), "num_predict": input.get("maxTokens", 512)}}
    if input.get("jsonOutput"):
        body["format"] = "json"
    r = requests.post(url, json=body, timeout=180)
    r.raise_for_status()
    text = (r.json().get("message") or {}).get("content", "")
    if input.get("jsonOutput"):
        try:
            return {"result": json.loads(text)}
        except ValueError:
            return {"result": text}
    return {"result": text}


def _loop(api, worker_id):
    while True:
        try:
            r = requests.get("%s/tasks/poll/%s" % (api, TASK), params={"workerid": worker_id}, timeout=30)
            if r.status_code != 200 or not r.content:
                time.sleep(0.2)
                continue
            task = r.json()
        except (requests.RequestException, ValueError):
            time.sleep(2)
            continue
        result = {"workflowInstanceId": task["workflowInstanceId"], "taskId": task["taskId"], "workerId": worker_id}
        try:
            result.update(status="COMPLETED", outputData=chat(task.get("inputData") or {}))
        except Exception as e:  # task FAILED with the error text; Conductor retries (retryCount 2)
            result.update(status="FAILED", reasonForIncompletion="%s: %s" % (type(e).__name__, e))
        for _ in range(3):
            try:
                requests.post(api + "/tasks", json=result, timeout=15).raise_for_status()
                break
            except requests.RequestException:
                time.sleep(1)


def main():
    api = config.get("CONDUCTOR_SERVER_URL").rstrip("/")
    print("convo_llm_chat worker polling %s (Ollama %s)" % (api, config.get("OLLAMA_URL")), flush=True)
    for i in range(4):
        threading.Thread(target=_loop, args=(api, "%s-%d" % (socket.gethostname(), i)), daemon=True).start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()

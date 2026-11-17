"""
Lab 05 — kyc_sanctions_screening worker.

Replaces the INLINE `sanctions_check` task in kyc_onboarding (v4).
Fill in each TODO yourself. Hints are in the comments.
"""

import difflib  # stdlib: fuzzy string similarity (0.0 = different, 1.0 = identical)

from conductor.client.automator.task_handler import TaskHandler      # runs the poll loop
from conductor.client.configuration.configuration import Configuration  # server URL + keys
from conductor.client.worker.worker_task import worker_task          # marks a fn as a worker

# Fake watchlist for the lab. In real life: OFAC list, a vendor API, or a database.
WATCHLIST = ["Ivan Petrovsky", "Global Shell Trading LLC", "Maria Lopes"]


# Must match the task definition name in Conductor exactly — it's the queue name.
@worker_task(task_definition_name="kyc_sanctions_screening")
def screen_applicant(name: str) -> dict:
    best_match, best_score = None, 0.0
    for entry in WATCHLIST:
        score = difflib.SequenceMatcher(None, name.lower(), entry.lower()).ratio()
        if score > best_score:
            best_match, best_score = entry, score

    hit = best_score >= 0.85
    print(f"Screened '{name}': closest '{best_match}' score {best_score:.2f} hit={hit}")

    # This dict becomes the task's output. compute_risk reads `sanctionsHit`.
    return {
        "sanctionsHit": hit,
        "matchScore": round(best_score, 2),
        "matchedName": best_match if hit else None,
    }


if __name__ == "__main__":
    config = Configuration()  # reads CONDUCTOR_SERVER_URL / _AUTH_KEY / _AUTH_SECRET from env
    handler = TaskHandler(configuration=config, scan_for_annotated_workers=True)
    handler.start_processes()  # one background process per worker, each polling its queue
    handler.join_processes()   # keep the main script alive (Ctrl+C to stop)

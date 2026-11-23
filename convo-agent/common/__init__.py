"""Shared platform code for all convo-agent versions (config, Conductor client, registrar, LLM worker, launcher)."""
import os

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # convo-agent/
REPO_DIR = os.path.dirname(APP_DIR)
RUN_DIR = os.path.join(APP_DIR, ".run")

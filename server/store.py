"""Almacén JSON atómico con lock de hilos para history.json."""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(BASE), "data")
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")

_lock = threading.Lock()


def _ensure() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump([], f)


def _read() -> list[dict[str, Any]]:
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write(items: list[dict[str, Any]]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = HISTORY_PATH + f".tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, HISTORY_PATH)


def load_history() -> list[dict[str, Any]]:
    with _lock:
        _ensure()
        return _read()


def upsert_job(job: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        _ensure()
        items = _read()
        for i, existing in enumerate(items):
            if existing.get("id") == job.get("id"):
                items[i] = {**existing, **job}
                _write(items)
                return items[i]
        items.insert(0, job)
        _write(items)
        return job


def merge_job(job_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    with _lock:
        _ensure()
        items = _read()
        for i, existing in enumerate(items):
            if existing.get("id") == job_id:
                items[i] = {**existing, **patch}
                _write(items)
                return items[i]
        return None


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        _ensure()
        for j in _read():
            if j.get("id") == job_id:
                return j
        return None


def remove_job(job_id: str) -> None:
    with _lock:
        _ensure()
        items = [j for j in _read() if j.get("id") != job_id]
        _write(items)


def clear_jobs(statuses: tuple[str, ...] = ("success", "failed", "cancelled")) -> int:
    with _lock:
        _ensure()
        items = _read()
        kept = [j for j in items if j.get("status") not in statuses]
        removed = len(items) - len(kept)
        if removed:
            _write(kept)
        return removed


def cancel_all_pending() -> int:
    with _lock:
        _ensure()
        items = _read()
        cnt = 0
        kept = []
        for j in items:
            st = j.get("status")
            if st == "pending":
                cnt += 1
                continue
            elif st == "running":
                j["status"] = "cancelled"
                j["stage"] = "Cancelado"
                j["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                cnt += 1
            kept.append(j)
        if cnt:
            _write(kept)
        return cnt

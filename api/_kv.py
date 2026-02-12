"""
Shared Upstash KV (Redis) helpers for serverless functions.

Provides generic get/set/delete and list-push/list-read operations
used by the question-reporting system and goals.
"""

import json
import os

import requests

KV_URL = os.environ.get("KV_REST_API_URL", "")
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN", "")


def _headers():
    return {"Authorization": f"Bearer {KV_TOKEN}"}


# ---------------------------------------------------------------------------
# Low-level primitives
# ---------------------------------------------------------------------------

def kv_get(key: str):
    """Read a key from KV. Returns parsed JSON value, or None."""
    if not KV_URL or not KV_TOKEN:
        return None
    try:
        resp = requests.get(
            f"{KV_URL}/get/{key}",
            headers=_headers(),
            timeout=10,
        )
        data = resp.json()
        result = data.get("result")
        if result is not None:
            try:
                return json.loads(result)
            except (json.JSONDecodeError, TypeError):
                return result
    except Exception:
        pass
    return None


def kv_set(key: str, value) -> bool:
    """Write a key to KV. Value is JSON-serialised. Returns True on success."""
    if not KV_URL or not KV_TOKEN:
        return False
    try:
        resp = requests.post(
            KV_URL,
            headers={**_headers(), "Content-Type": "application/json"},
            json=["SET", key, json.dumps(value)],
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


def kv_delete(key: str) -> bool:
    """Delete a key from KV."""
    if not KV_URL or not KV_TOKEN:
        return False
    try:
        resp = requests.post(
            KV_URL,
            headers={**_headers(), "Content-Type": "application/json"},
            json=["DEL", key],
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Convenience: list-like operations (stored as JSON arrays)
# ---------------------------------------------------------------------------

def kv_list_get(key: str) -> list:
    """Read a list stored as a JSON array. Returns [] if missing."""
    val = kv_get(key)
    if isinstance(val, list):
        return val
    return []


def kv_list_push(key: str, item) -> bool:
    """Append an item to a JSON-array list in KV."""
    lst = kv_list_get(key)
    lst.append(item)
    return kv_set(key, lst)


def kv_list_remove(key: str, item) -> bool:
    """Remove first occurrence of item from a JSON-array list."""
    lst = kv_list_get(key)
    try:
        lst.remove(item)
    except ValueError:
        return True  # already absent
    return kv_set(key, lst)

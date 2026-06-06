"""Smithery directory client.

`PUT https://api.smithery.ai/servers/<namespace>%2F<name>` — idempotent.
Body: {displayName, description}. Auth: Bearer $SMITHERY_API_KEY.

Also exposes `probe_listed` for the audit's network probe (24h cache).
"""

from __future__ import annotations

import os
from typing import Optional

import requests


def publish(namespace: str, name: str, display_name: str, description: str,
            api_key: Optional[str] = None,
            session: Optional[requests.Session] = None) -> dict:
    """PUT the server's display card to Smithery. Idempotent.

    Returns a dict the cross_post orchestrator can adapt to DirectoryResult.
    """
    api_key = api_key or os.environ.get("SMITHERY_API_KEY")
    if not api_key:
        return {
            "ok": False,
            "status_code": None,
            "message": "SMITHERY_API_KEY env var not set. "
                       "Get one at https://smithery.ai/account/api-keys",
        }

    url = f"https://api.smithery.ai/servers/{namespace}%2F{name}"
    sess = session or requests
    try:
        resp = sess.put(
            url,
            json={"displayName": display_name, "description": description},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
    except requests.RequestException as e:
        return {"ok": False, "status_code": None, "message": f"connection error: {e}"}

    status = resp.status_code
    if 200 <= status < 300:
        if status == 201:
            return {"ok": True, "status_code": 201, "message": "published"}
        if status == 200:
            return {"ok": True, "status_code": 200, "message": "updated (already exists, idempotent)"}
        return {"ok": True, "status_code": status, "message": f"HTTP {status}"}

    if status == 401:
        return {"ok": False, "status_code": 401,
                "message": "auth failed (401). Check SMITHERY_API_KEY is valid."}
    if status == 403:
        return {"ok": False, "status_code": 403,
                "message": f"forbidden (403). Does your token own the '{namespace}' namespace?"}
    if status == 429:
        return {"ok": False, "status_code": 429,
                "message": "rate-limited (429). Retry later."}

    return {"ok": False, "status_code": status,
            "message": f"Smithery API error: HTTP {status}. {resp.text[:500]}"}


def probe_listed(namespace: str, name: str,
                 session: Optional[requests.Session] = None) -> dict:
    """Probe Smithery for the server's listing status (for the audit)."""
    if os.environ.get("MEOK_ALLOW_NETWORK") != "1":
        return {"listed": False, "reason": "network disabled"}

    url = f"https://registry.smithery.ai/servers/{namespace}/{name}"
    sess = session or requests
    try:
        resp = sess.get(url, headers={"Accept": "application/json"}, timeout=10)
    except requests.RequestException as e:
        return {"listed": False, "reason": f"connection error: {e}"}

    if 200 <= resp.status_code < 300:
        return {"listed": True, "status_code": resp.status_code}
    return {"listed": False, "status_code": resp.status_code, "reason": f"HTTP {resp.status_code}"}

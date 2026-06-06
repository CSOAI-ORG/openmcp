"""MCP Registry directory client.

`POST https://registry.modelcontextprotocol.io/v0/publish` — needs a
short-lived JWT exchanged from a GitHub OAuth token.

Auth flow (per the MCP Registry spec):
  1. POST /v0/auth/github/exchange with {github_token: <PAT>} → {jwt: <short>}
  2. POST /v0/publish with Authorization: Bearer <jwt> and a ServerJSON body

Idempotency: 409 Conflict on (name, version) repeat is treated as success.
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

import requests


def _github_token() -> Optional[str]:
    """Get the GitHub PAT. Prefer keyring (per AGENTS.md); fall back to env."""
    try:
        import keyring
        token = keyring.get_password("meok-cross-post", "github-pat")
        if token:
            return token
    except (ImportError, Exception):
        pass
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def exchange_jwt(github_token: str,
                 session: Optional[requests.Session] = None) -> Tuple[Optional[str], str]:
    """Exchange a GitHub PAT for a short-lived registry JWT."""
    url = "https://registry.modelcontextprotocol.io/v0/auth/github/exchange"
    sess = session or requests
    try:
        resp = sess.post(
            url, json={"github_token": github_token},
            headers={"Content-Type": "application/json"}, timeout=30,
        )
    except requests.RequestException as e:
        return None, f"connection error during JWT exchange: {e}"

    if 200 <= resp.status_code < 300:
        return resp.json().get("jwt"), "JWT minted"

    if resp.status_code == 401:
        return None, f"JWT exchange auth failed (401). Body: {resp.text[:500]}"
    return None, f"JWT exchange error: HTTP {resp.status_code}. {resp.text[:500]}"


def publish(server_json: dict,
            session: Optional[requests.Session] = None) -> dict:
    """Publish a ServerJSON to the MCP Registry. 409 is treated as success."""
    token = _github_token()
    if not token:
        return {
            "ok": False,
            "status_code": None,
            "message": "GITHUB_TOKEN env var not set AND no keyring entry. "
                       "Run `meok-cross-post auth bootstrap` to store a PAT in keyring.",
        }

    jwt, msg = exchange_jwt(token, session=session)
    if not jwt:
        return {"ok": False, "status_code": 401, "message": msg}

    url = "https://registry.modelcontextprotocol.io/v0/publish"
    sess = session or requests
    try:
        resp = sess.post(
            url, json=server_json,
            headers={
                "Authorization": f"Bearer {jwt}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
    except requests.RequestException as e:
        return {"ok": False, "status_code": None, "message": f"connection error: {e}"}

    status = resp.status_code
    if 200 <= status < 300:
        if status == 201:
            return {"ok": True, "status_code": 201, "message": "created"}
        return {"ok": True, "status_code": status, "message": "updated"}

    if status == 409:
        return {
            "ok": True,                                  # idempotent success
            "status_code": 409,
            "message": "already published (idempotent — same name + version)",
        }
    if status == 401:
        return {
            "ok": False, "status_code": 401,
            "message": "JWT expired or invalid. Retry — fresh JWTs are short-lived.",
        }
    if status == 403:
        return {
            "ok": False, "status_code": 403,
            "message": f"forbidden — namespace ownership mismatch. "
                       f"Is '{server_json.get('name', '?')}' owned by your GitHub user?",
        }
    if status == 422:
        return {
            "ok": False, "status_code": 422,
            "message": f"schema/semantic validation failed. Body: {resp.text[:500]}",
        }
    if status == 429:
        return {"ok": False, "status_code": 429,
                "message": "rate-limited (429). Retry later."}
    return {"ok": False, "status_code": status,
            "message": f"MCP Registry error: HTTP {status}. {resp.text[:500]}"}


def probe_listed(server_name: str,
                 session: Optional[requests.Session] = None) -> dict:
    """Probe the registry for the server's listing (for the audit)."""
    if os.environ.get("MEOK_ALLOW_NETWORK") != "1":
        return {"listed": False, "reason": "network disabled"}

    url = f"https://registry.modelcontextprotocol.io/v0/servers/{server_name}"
    sess = session or requests
    try:
        resp = sess.get(url, timeout=10)
    except requests.RequestException as e:
        return {"listed": False, "reason": f"connection error: {e}"}

    if 200 <= resp.status_code < 300:
        return {"listed": True, "status_code": resp.status_code}
    return {"listed": False, "status_code": resp.status_code, "reason": f"HTTP {resp.status_code}"}

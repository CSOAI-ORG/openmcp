#!/usr/bin/env python3
"""Real end-to-end test for the meok-cross-post (openMCP) MCP server.

Boots ``server.py`` over the streamable-HTTP transport in a subprocess,
connects with the official MCP streamable-HTTP client, lists the tools,
and CALLS every tool once with a minimal valid argument — proving the
server is operationally live, not just unit-green.

This is a standalone script, NOT a pytest module. The repo's pytest config
sets ``python_files = "test_*.py"``, so ``e2e_server.py`` is never collected
by the normal ``pytest tests/`` run (it needs a live server). Invoke it
explicitly::

    python tests/e2e_server.py

Exits 0 on success (with a clear pass line per tool) and non-zero on any
failure. The server subprocess is always killed in a ``finally`` block.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_PY = REPO_ROOT / "server.py"

EXPECTED_TOOLS = {
    "audit_repo",
    "cross_post_metadata",
    "manual_checklist",
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_ready(host: str, port: int, proc: subprocess.Popen, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"server exited early with code {proc.returncode} before becoming ready"
            )
        if _port_open(host, port):
            return
        time.sleep(0.25)
    raise TimeoutError(f"server did not open {host}:{port} within {timeout}s")


def _check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _content_text(result) -> str:
    parts = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    return "\n".join(parts)


def _payload(result):
    """Return the tool's structured payload (dict) or raw text.

    Newer FastMCP fills ``structuredContent``; older builds only serialise the
    return value into a JSON / text block. ``manual_checklist`` returns a
    markdown string, so the text form is returned as-is when it is not JSON.
    """
    if result.structuredContent:
        return result.structuredContent
    text = _content_text(result).strip()
    if text:
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return text
    return None


async def _exercise(host: str, port: int, sample_repo: str) -> None:
    url = f"http://{host}:{port}/mcp"
    async with streamablehttp_client(url) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("PASS  initialize: session established")

            listed = await session.list_tools()
            names = {t.name for t in listed.tools}
            missing = EXPECTED_TOOLS - names
            _check(not missing, f"missing expected tools: {missing}")
            print(f"PASS  list_tools: all expected tools present ({sorted(names)})")

            # 1) audit_repo — score a real repo 0-100 (network probes off).
            r = await session.call_tool(
                "audit_repo", {"path": sample_repo, "allow_network": False}
            )
            _check(not r.isError, f"audit_repo errored: {_content_text(r)}")
            sc = _payload(r)
            _check(
                isinstance(sc, dict) and ("score" in sc or "total" in sc or "gate" in sc),
                f"audit_repo unexpected shape: {sc!r}",
            )
            print(f"PASS  audit_repo -> {sorted(sc)[:6]}")

            # 2) cross_post_metadata — runs preflight (no creds => safe no-op).
            r = await session.call_tool("cross_post_metadata", {"path": sample_repo})
            _check(not r.isError, f"cross_post_metadata errored: {_content_text(r)}")
            sc = _payload(r)
            _check(isinstance(sc, dict) and bool(sc), f"cross_post_metadata empty: {sc!r}")
            print(f"PASS  cross_post_metadata -> {sorted(sc)[:6]}")

            # 3) manual_checklist — returns markdown for the manual directories.
            r = await session.call_tool("manual_checklist", {"path": sample_repo})
            _check(not r.isError, f"manual_checklist errored: {_content_text(r)}")
            sc = _payload(r)
            text = sc if isinstance(sc, str) else _content_text(r)
            _check(bool(text) and len(text) > 10, f"manual_checklist too short: {text!r}")
            print(f"PASS  manual_checklist -> {len(text)} chars of markdown")


def _make_sample_repo() -> str:
    """A minimal repo dir so audit_repo has something concrete to score."""
    d = Path(tempfile.mkdtemp(prefix="e2e-xp-repo-"))
    (d / "README.md").write_text("# sample-mcp\n\nA sample MCP server.\n", encoding="utf-8")
    (d / "server.py").write_text(
        'from mcp.server.fastmcp import FastMCP\nmcp = FastMCP("sample")\n',
        encoding="utf-8",
    )
    (d / "pyproject.toml").write_text(
        '[project]\nname = "sample-mcp"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    return str(d)


def main() -> int:
    host = "127.0.0.1"
    port = _free_port()

    tmp_home = tempfile.mkdtemp(prefix="e2e-xp-home-")
    sample_repo = _make_sample_repo()

    env = dict(os.environ)
    env["HOME"] = tmp_home
    # Hermeticity (per AGENTS.md): never touch the real ~/.meok / keyring.
    env["XDG_CONFIG_HOME"] = str(Path(tmp_home) / ".config")
    env["XDG_CACHE_HOME"] = str(Path(tmp_home) / ".cache")
    env.pop("MEOK_ALLOW_NETWORK", None)
    # server.main() reads PORT and binds 0.0.0.0; we connect on 127.0.0.1.
    env["PORT"] = str(port)

    proc = subprocess.Popen(
        [sys.executable, str(SERVER_PY)],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        try:
            _wait_ready(host, port, proc)
        except Exception:
            try:
                out = proc.stdout.read().decode("utf-8", "replace") if proc.stdout else ""
            except Exception:
                out = ""
            print("--- server output ---", file=sys.stderr)
            print(out, file=sys.stderr)
            raise
        print(f"PASS  boot: server live on http://{host}:{port}/mcp (pid {proc.pid})")
        asyncio.run(_exercise(host, port, sample_repo))
        print("\nE2E OK: all meok-cross-post tools answered over streamable-HTTP")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"\nE2E FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())

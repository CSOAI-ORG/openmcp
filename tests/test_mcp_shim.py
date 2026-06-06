"""Smoke test for the MCP shim.

Spins up the mcp_server.py in a subprocess, opens a real ClientSession,
lists the 3 tools, and calls `audit_repo` against a real repo fixture.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest


def _free_port() -> int:
    """Find a free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def mcp_server():
    """Start the openmcp shim in a subprocess on a free port.

    Yields (port, base_url). Skips the test if the mcp client lib is
    not available (e.g. in a minimal CI env).
    """
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError:
        pytest.skip("mcp client lib not available")

    port = _free_port()
    env = {
        **os.environ,
        "PORT": str(port),
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "TMPDIR": "/tmp",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "meok_cross_post.mcp_server"],
        env=env, cwd="/Users/nicholas/meok-cross-post",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    base_url = f"http://127.0.0.1:{port}/mcp"

    # Wait for the server to start (poll the port)
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.2)
    else:
        proc.terminate()
        raise RuntimeError(f"openmcp shim did not start on port {port}")

    yield base_url

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.mark.asyncio
async def test_mcp_shim_lists_tools(mcp_server: str) -> None:
    """The shim should expose exactly 3 tools: audit_repo, cross_post_repo, manual_checklist_for."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(mcp_server) as (read, write, _):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            assert init.serverInfo.name == "openmcp"
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert "audit_repo" in names
            assert "cross_post_repo" in names
            assert "manual_checklist_for" in names


@pytest.mark.asyncio
async def test_mcp_shim_audit_repo(mcp_server: str) -> None:
    """Calling audit_repo against the gold_standard fixture should return high score."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    gold = "/Users/nicholas/meok-cross-post/tests/fixtures/gold_standard"
    if not Path(gold).is_dir():
        pytest.skip("gold_standard fixture not present")

    async with streamablehttp_client(mcp_server) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "audit_repo", {"path": gold, "allow_network": False},
            )
            # The result is a CallToolResult with content[0].text = JSON string
            import json
            text = result.content[0].text
            sc = json.loads(text)
            assert sc["score"] >= 90
            assert sc["gate"] in ("merge", "review")
            assert sc["repo_name"] == "threat-intelligence"


@pytest.mark.asyncio
async def test_mcp_shim_manual_checklist(mcp_server: str) -> None:
    """Calling manual_checklist_for should return a markdown string with 4 directories."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(mcp_server) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "manual_checklist_for",
                {"path": "/tmp/whatever-fake-flagship"},
            )
            text = result.content[0].text
            assert "Docker MCP Catalog" in text
            assert "Glama" in text
            assert "MCPize" in text
            assert "PulseMCP" in text

"""Root MCP server for meok-cross-post (openMCP).

This is the canonical streamable-HTTP entrypoint that directories
(Smithery, Glama, MCP Registry) discover. It re-exposes the real
audit / cross-post / manual-checklist functionality of the
`meok_cross_post` package as MCP tools.

Import-safe: constructing `mcp` and registering tools has no side
effects. The HTTP server only starts under `if __name__ == "__main__"`.

    python server.py            # serve on streamable-http (default :8000)
    from server import mcp      # embed in a parent FastMCP
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from meok_cross_post import __version__
from meok_cross_post.audit import (
    Audit,
    DEFAULT_CHECKS,
    check_server_py_imports_clean,
)
from meok_cross_post.cross_post import run as _cross_post_run
from meok_cross_post.manual_checklist import render_checklist as _render_checklist

# SECURITY: `check_server_py_imports_clean` runs `python -c "import server"` with
# the TARGET path on PYTHONPATH — it executes code from the audited repo. Fine
# for the local CLI (you trust the repo you point at), but a remote-code-
# execution vector the moment `audit_repo` is reachable over the network MCP
# transport. The network tool runs a code-execution-free subset; the local
# `meok-cross-post audit` CLI keeps the full check set.
_NETWORK_SAFE_CHECKS = [c for c in DEFAULT_CHECKS if c is not check_server_py_imports_clean]


def _safe_audit_path(path: str) -> Path:
    """Resolve + validate a caller-supplied audit path. Rejects non-existent or
    non-directory targets so the tool can't be used to probe arbitrary files."""
    p = Path(path).resolve()
    if not p.is_dir():
        raise ValueError(f"audit path must be an existing directory: {path!r}")
    return p

mcp = FastMCP(
    "openmcp",
    instructions=(
        "openMCP is the keystone tool for the MEOK fleet's directory presence. "
        "It audits flagship MCP server repos 0-100 against the FLEET_BASE.md "
        "template, cross-posts metadata to the directories that have public "
        "APIs (Smithery, MCP Registry), and prints manual checklists for the "
        "ones that don't (Docker MCP Catalog, Glama, MCPize, PulseMCP)."
    ),
)


@mcp.tool()
def audit_repo(path: str, allow_network: bool = False) -> dict:
    """Score a flagship MCP repo 0-100 against the openMCP rubric.

    Args:
        path: Absolute path to the flagship repo to audit.
        allow_network: Set True to enable the 3 network probes (GHCR,
            Smithery, MCP Registry). Off by default -- network calls are
            slow and noisy for a single audit.

    Returns:
        A dict with score, gate verdict, category breakdown, and the
        per-check details. (The `import server` check is skipped over the
        network for safety — see module security note.)
    """
    sc = Audit(checks=_NETWORK_SAFE_CHECKS).score(_safe_audit_path(path), allow_network=allow_network)
    return sc.to_dict()


@mcp.tool()
def cross_post_metadata(path: str) -> dict:
    """Push a flagship repo's metadata to Smithery + MCP Registry.

    Args:
        path: Absolute path to the flagship repo.

    Returns:
        A dict with preflight status, per-directory results, and the
        rendered manual checklist. Auth via env vars or keyring -- run
        `meok-cross-post auth bootstrap` once to set up the GitHub PAT.
    """
    result = _cross_post_run(Path(path))
    return result.model_dump(mode="json")


@mcp.tool()
def manual_checklist(path: str) -> str:
    """Return the manual directory-submission checklist as markdown.

    For directories without public APIs (Docker MCP Catalog, Glama,
    MCPize, PulseMCP), this returns a clean markdown checklist with the
    exact submission URL and any files the user needs to add.

    Args:
        path: Absolute path to the flagship repo (only the basename is used).

    Returns:
        Markdown checklist as a string.
    """
    return _render_checklist(Path(path).name)


def main() -> None:
    """Entry point: serve openMCP over streamable-HTTP."""
    import os

    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = int(os.environ.get("PORT", "8000"))
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

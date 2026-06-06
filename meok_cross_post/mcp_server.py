"""MCP server shim for meok-cross-post.

Exposes the same 3 tools that the CLI uses, so an MCP-aware agent can
drive the audit + cross-post + manual checklist workflow over
streamable-HTTP.

Usage:
    openmcp                                            # starts on $PORT (default 8000)
    # Or import and add to a parent FastMCP:
    from meok_cross_post.mcp_server import mcp as openmcp
"""

from __future__ import annotations

import os
from typing import Optional

from mcp.server.fastmcp import FastMCP

from meok_cross_post import __version__
from meok_cross_post.audit import score as audit_score
from meok_cross_post.cross_post import run as cross_post_run
from meok_cross_post.manual_checklist import render_checklist

mcp = FastMCP(
    "openmcp",
    instructions=(
        "openMCP is the keystone tool for the MEOK fleet's directory presence. "
        "It audits flagship MCP server repos 0-100 against the FLEET_BASE.md "
        "template, cross-posts metadata to the directories that have public APIs "
        "(Smithery, MCP Registry), and prints manual checklists for the ones that "
        "don't (Docker MCP Catalog, Glama, MCPize, PulseMCP)."
    ),
)


@mcp.tool()
def audit_repo(path: str, allow_network: bool = False) -> dict:
    """Score a flagship MCP repo 0-100 against FLEET_BASE.md.

    Args:
        path: Absolute path to the flagship repo.
        allow_network: Set True to enable 3 network probes (GHCR, Smithery,
                       MCP Registry). Off by default — network calls are slow
                       and noisy for a single audit call.

    Returns:
        A dict with score, gate verdict, category breakdown, and per-check
        details. To render as markdown, call `scorecard_markdown(result)`.
    """
    if allow_network:
        os.environ["MEOK_ALLOW_NETWORK"] = "1"
    from pathlib import Path
    sc = audit_score(Path(path), allow_network=allow_network)
    return sc.to_dict()


@mcp.tool()
def cross_post_repo(path: str) -> dict:
    """Push a flagship repo's metadata to Smithery + MCP Registry.

    Args:
        path: Absolute path to the flagship repo.

    Returns:
        A dict with preflight status, per-directory results, and the
        rendered manual checklist. Auth via env vars or keyring — run
        `meok-cross-post auth bootstrap` once to set up the GitHub PAT.
    """
    from pathlib import Path
    result = cross_post_run(Path(path))
    return result.model_dump(mode="json")


@mcp.tool()
def manual_checklist_for(path: str) -> str:
    """Return the manual directory submission checklist as markdown.

    For directories without public APIs (Docker MCP Catalog, Glama,
    MCPize, PulseMCP), this returns a clean markdown checklist with the
    exact URL and any files the user needs to add. The 2 directories
    with public APIs (Smithery, MCP Registry) are NOT in this list —
    use `cross_post_repo` for those.

    Args:
        path: Absolute path to the flagship repo (only the basename is used).

    Returns:
        Markdown checklist as a string.
    """
    from pathlib import Path
    repo_name = Path(path).name
    return render_checklist(repo_name)


def main() -> None:
    """Entry point for `openmcp` script (defined in pyproject.toml)."""
    import os as _os
    port = int(_os.environ.get("PORT", "8000"))
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = port
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()

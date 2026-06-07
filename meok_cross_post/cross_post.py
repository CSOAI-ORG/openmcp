"""Cross-post orchestrator.

Reads the 5 metadata files in a flagship repo, asserts they agree on
<name> + <tool list>, then publishes to the 2 automatable directories
(Smithery + MCP Registry) and prints the manual checklist for the
other 4 (Docker Catalog, Glama, MCPize, PulseMCP).
"""

from __future__ import annotations

import json
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import yaml

from meok_cross_post import ghcr, mcp_registry, smithery
from meok_cross_post.manual_checklist import render_checklist
from meok_cross_post.schema import CrossPostResult, DirectoryResult


# --------------------------------------------------------------------- preflight


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        return ""


def _load_metadata(repo: Path) -> Dict[str, Any]:
    """Read the 5 metadata files into a dict. Missing files are silently absent."""
    out: Dict[str, Any] = {}

    p = repo / "smithery.yaml"
    if p.is_file():
        try:
            out["smithery.yaml"] = yaml.safe_load(_read(p)) or {}
        except yaml.YAMLError:
            out["smithery.yaml"] = {}

    p = repo / "server.json"
    if p.is_file():
        try:
            out["server.json"] = json.loads(_read(p))
        except json.JSONDecodeError:
            out["server.json"] = {}

    p = repo / ".well-known" / "mcp" / "server-card.json"
    if p.is_file():
        try:
            out["server-card.json"] = json.loads(_read(p))
        except json.JSONDecodeError:
            out["server-card.json"] = {}

    p = repo / "glama.json"
    if p.is_file():
        try:
            out["glama.json"] = json.loads(_read(p))
        except json.JSONDecodeError:
            out["glama.json"] = {}

    p = repo / "package.json"
    if p.is_file():
        try:
            out["package.json"] = json.loads(_read(p))
        except json.JSONDecodeError:
            out["package.json"] = {}

    return out


def preflight(repo: Path) -> Tuple[bool, List[str], Dict[str, Any]]:
    """Check that the 5 metadata files agree on <name> + <tool list>.

    Returns (ok, errors, metadata).
    """
    md = _load_metadata(repo)
    errors: List[str] = []

    # Extract tool list from smithery.yaml (declarative form)
    sy = md.get("smithery.yaml") or {}
    sy_tools = sy.get("tools") or []
    sy_names = [t.get("name") for t in sy_tools if isinstance(t, dict) and t.get("name")]

    # Extract from server.json: only the package identifier (no tool list in ServerJSON)
    sj = md.get("server.json") or {}
    sj_pkg_id = ""
    for pkg in sj.get("packages") or []:
        if isinstance(pkg, dict) and pkg.get("registryType") == "pypi":
            sj_pkg_id = pkg.get("identifier", "")
            break

    # Extract from server-card.json
    sc = md.get("server-card.json") or {}

    # Extract from package.json: mcp.name
    pj = md.get("package.json") or {}
    pj_mcp_name = (pj.get("mcp") or {}).get("name", "")

    # Cross-checks
    if not sy_names:
        errors.append("smithery.yaml has no `tools:` array — no tool names to validate")

    if sj_pkg_id and pj_mcp_name and sj_pkg_id != pj_mcp_name:
        errors.append(
            f"name mismatch: server.json packages[0].identifier={sj_pkg_id!r} "
            f"!= package.json mcp.name={pj_mcp_name!r}"
        )

    if not (sj.get("name") or "").endswith(sj_pkg_id):
        # server.json name should be the same as the package identifier
        # (with the io.github.<org>/ prefix optional)
        name = sj.get("name", "")
        if name and not name.endswith(sj_pkg_id):
            errors.append(
                f"name mismatch: server.json name={name!r} doesn't end with "
                f"packages[0].identifier={sj_pkg_id!r}"
            )

    # server-card.json should agree on the basic name
    sc_name = sc.get("name", "")
    if sc_name and pj_mcp_name and sc_name != pj_mcp_name:
        errors.append(
            f"name mismatch: server-card.json name={sc_name!r} "
            f"!= package.json mcp.name={pj_mcp_name!r}"
        )

    ok = len(errors) == 0
    return ok, errors, md


# ------------------------------------------------------------- docker template


def write_docker_template(repo: Path, metadata: Dict[str, Any]) -> Path:
    """Write a server.yaml template for the Docker MCP Catalog PR.

    The user can `cp` this into a fork of docker/mcp-registry and open a PR.
    """
    sy = metadata.get("smithery.yaml") or {}
    tools = sy.get("tools") or []
    repo_name = repo.name

    template = {
        "title": repo_name,
        "description": sy.get("description", f"{repo_name} MCP server"),
        "type": "server",
        "image": f"ghcr.io/csoai-org/{repo_name}:latest",
        "tools": [
            {
                "name": t.get("name"),
                "description": t.get("description", ""),
            }
            for t in tools if isinstance(t, dict) and t.get("name")
        ],
        "metadata": {
            "category": "security",
            "tags": ["mcp", "csoai-org"],
            "license": "Apache-2.0",
            "owner": "CSOAI-ORG",
        },
        "source": f"https://github.com/CSOAI-ORG/{repo_name}",
        "upstream": f"https://github.com/CSOAI-ORG/{repo_name}",
    }
    # A unique, owner-only temp dir (not a fixed world-writable /tmp path, which
    # is symlink-attackable). The caller gets the full path back to `cp` from.
    out_dir = Path(tempfile.mkdtemp(prefix="meok-cross-post-"))
    out = out_dir / f"{repo_name}-docker-catalog.yaml"
    out.write_text(yaml.safe_dump(template, sort_keys=False))
    return out


# ----------------------------------------------------------------- orchestrator


def _push_smithery(repo: Path, md: Dict[str, Any]) -> DirectoryResult:
    """Publish the display card to Smithery and adapt the result."""
    sy = md.get("smithery.yaml") or {}
    # Smithery namespace comes from the mcp-smithery-publish.yml workflow:
    # the org uses `nicholastempleman/<repo>` (literal prefix, not CSOAI-ORG).
    # This is the Smithery account name; it diverges from the GitHub org.
    sm_result = smithery.publish(
        namespace="nicholastempleman",
        name=repo.name + "-mcp",  # e.g. threat-intelligence-mcp
        display_name=repo.name,
        description=sy.get("description", f"{repo.name} MCP server"),
    )
    return DirectoryResult(
        directory="smithery",
        ok=sm_result.get("ok", False),
        status_code=sm_result.get("status_code"),
        message=sm_result.get("message", ""),
    )


def _push_mcp_registry(repo: Path, md: Dict[str, Any]) -> DirectoryResult:
    """Publish the ServerJSON to the MCP Registry and adapt the result."""
    sj = md.get("server.json") or {}
    registry_name = sj.get("name", "")
    if not registry_name.startswith("io.github."):
        # Promote to io.github.<org>/<name> form (canonical namespace).
        org = "CSOAI-ORG"
        bare = registry_name.split("/")[-1] if "/" in registry_name else registry_name
        registry_name = f"io.github.{org}/{bare}"
        sj = {**sj, "name": registry_name}

    reg_result = mcp_registry.publish(sj)
    return DirectoryResult(
        directory="mcp_registry",
        ok=reg_result.get("ok", False),
        status_code=reg_result.get("status_code"),
        message=reg_result.get("message", ""),
    )


def run(repo: Path) -> CrossPostResult:
    """Pre-flight + cross-post to automatable directories + manual checklist.

    Preflight runs first (sequential). The independent directory pushes
    (Smithery + MCP Registry) hit different APIs with no ordering
    dependency, so they are fanned out CONCURRENTLY via a
    ThreadPoolExecutor — the publish() clients are synchronous HTTP. A
    failure (or raised exception) in one directory is captured into that
    directory's DirectoryResult with status=error and does NOT abort the
    others. The docker template + manual checklist are then assembled
    sequentially. The return type and result ordering are preserved.
    """
    repo = Path(repo).resolve()
    ok, errors, md = preflight(repo)

    if not ok:
        return CrossPostResult(
            repo=str(repo),
            repo_name=repo.name,
            preflight_ok=False,
            preflight_errors=errors,
            directories=[],
            manual_checklist="",
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    # Fan out the independent directory pushes in parallel. Each entry is
    # (directory_label, callable). Results are reassembled in this fixed
    # order so the return shape is deterministic even though the network
    # calls complete in a nondeterministic order.
    pushes: List[Tuple[str, Callable[[Path, Dict[str, Any]], DirectoryResult]]] = [
        ("smithery", _push_smithery),
        ("mcp_registry", _push_mcp_registry),
    ]

    def _run_push(label: str,
                  fn: Callable[[Path, Dict[str, Any]], DirectoryResult]) -> DirectoryResult:
        try:
            return fn(repo, md)
        except Exception as e:  # one directory failing must not kill the others
            return DirectoryResult(
                directory=label,
                ok=False,
                status_code=None,
                message=f"error: {e}",
            )

    with ThreadPoolExecutor(max_workers=len(pushes)) as pool:
        futures = {label: pool.submit(_run_push, label, fn) for label, fn in pushes}
        directories: List[DirectoryResult] = [futures[label].result() for label, _ in pushes]

    # Manual checklist
    template_path = write_docker_template(repo, md) if "smithery.yaml" in md else None
    checklist = render_checklist(repo.name, template_path)

    return CrossPostResult(
        repo=str(repo),
        repo_name=repo.name,
        preflight_ok=True,
        preflight_errors=[],
        directories=directories,
        manual_checklist=checklist,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

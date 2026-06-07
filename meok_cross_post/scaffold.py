"""Safe static-discovery-file scaffolding for the `refine --scaffold` loop.

Generates the SAFE, declarative discovery files a flagship repo needs to
clear the audit's C_discovery / E_cicd gates — derived from the repo's
pyproject (name/description/version) and, when present, the `@mcp.tool`
functions in server.py. These are all static metadata files; this module
NEVER writes server.py and NEVER executes repo code.

Files it can create (only if missing):
  - smithery.yaml                          (declarative, `tools:` array)
  - server.json                            (MCP Registry schema + PyPI pkg)
  - .well-known/mcp/server-card.json
  - package.json                           (mcp.entry = server:main)
  - glama.json                             (CSOAI-ORG maintainer)
  - SECURITY.md                            (security@ contact)
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

# The set of files this module knows how to scaffold (in apply order).
SCAFFOLDABLE: Tuple[str, ...] = (
    "smithery.yaml",
    "server.json",
    ".well-known/mcp/server-card.json",
    "package.json",
    "glama.json",
    "SECURITY.md",
)

_ORG = "CSOAI-ORG"
_SECURITY_EMAIL = "security@meok.ai"
_TOOL_DEF_RE = re.compile(
    r"@mcp\.tool[^\n]*\n(?:@\w+[^\n]*\n)*\s*(?:async\s+)?def\s+([a-z_][a-z0-9_]*)\s*\(",
)


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        return ""


def project_meta(repo: Path) -> Dict[str, str]:
    """Pull name/description/version from pyproject.toml (best-effort)."""
    name = repo.name
    description = f"{repo.name} MCP server"
    version = "0.1.0"
    p = repo / "pyproject.toml"
    if p.is_file():
        try:
            data = tomllib.loads(_read(p))
        except tomllib.TOMLDecodeError:
            data = {}
        proj = data.get("project") or {}
        name = proj.get("name") or name
        description = proj.get("description") or description
        version = proj.get("version") or version
    return {"name": name, "description": description, "version": version}


def discover_tools(repo: Path) -> List[Dict[str, str]]:
    """Find @mcp.tool function names in server.py (static parse, no exec).

    Returns a list of {name, description} dicts. Falls back to a single
    placeholder tool so the declarative `tools:` array is never empty.
    """
    src = _read(repo / "server.py")
    names = _TOOL_DEF_RE.findall(src) if src else []
    # dedupe, preserve order
    seen: set[str] = set()
    ordered = [n for n in names if not (n in seen or seen.add(n))]
    if not ordered:
        ordered = ["run"]
    return [{"name": n, "description": f"{n} tool"} for n in ordered]


# ----------------------------------------------------------- template builders


def _smithery_yaml(meta: Dict[str, str], tools: List[Dict[str, str]]) -> str:
    doc: Dict[str, Any] = {
        "name": meta["name"],
        "displayName": meta["name"],
        "description": meta["description"],
        "license": "Apache-2.0",
        "startCommand": {"type": "http"},
        "tools": [{"name": t["name"], "description": t["description"]} for t in tools],
    }
    return yaml.safe_dump(doc, sort_keys=False)


def _server_json(meta: Dict[str, str]) -> str:
    bare = meta["name"]
    doc = {
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-07-09/server.schema.json",
        "name": f"io.github.{_ORG.lower()}/{bare}",
        "description": meta["description"],
        "version": meta["version"],
        "repository": {
            "url": f"https://github.com/{_ORG}/{bare}",
            "source": "github",
        },
        "packages": [
            {
                "registryType": "pypi",
                "registryBaseUrl": "https://pypi.org",
                "identifier": bare,
                "version": meta["version"],
                "transport": {"type": "streamable-http"},
            }
        ],
    }
    return json.dumps(doc, indent=2) + "\n"


def _server_card(meta: Dict[str, str], tools: List[Dict[str, str]]) -> str:
    doc = {
        "$schema": "https://schema.smithery.ai/server-card.json",
        "name": meta["name"],
        "description": meta["description"],
        "version": meta["version"],
        "vendor": "MEOK AI Labs",
        "homepage": f"https://github.com/{_ORG}/{meta['name']}",
        "transport": {"type": "streamable-http", "url": "http://localhost:8000/mcp"},
        "tools": [{"name": t["name"], "description": t["description"]} for t in tools],
    }
    return json.dumps(doc, indent=2) + "\n"


def _package_json(meta: Dict[str, str]) -> str:
    doc = {
        "name": meta["name"],
        "version": meta["version"],
        "description": meta["description"],
        "license": "Apache-2.0",
        "homepage": f"https://github.com/{_ORG}/{meta['name']}",
        "mcp": {"name": meta["name"], "entry": "server:main", "transport": "streamable-http"},
    }
    return json.dumps(doc, indent=2) + "\n"


def _glama_json(meta: Dict[str, str]) -> str:
    doc = {
        "$schema": "https://glama.ai/mcp/schemas/server.json",
        "maintainers": [_ORG],
    }
    return json.dumps(doc, indent=2) + "\n"


def _security_md(meta: Dict[str, str]) -> str:
    return (
        "# Security Policy\n\n"
        "## Reporting a Vulnerability\n\n"
        "Please report security vulnerabilities responsibly:\n\n"
        f"1. **Email**: {_SECURITY_EMAIL}\n"
        "2. **Do NOT** open a public GitHub issue for security vulnerabilities.\n"
        "3. Include a description and steps to reproduce.\n\n"
        "We acknowledge receipt within 48 hours.\n"
    )


def render(repo: Path, rel: str) -> str:
    """Render the template body for one scaffoldable file (no I/O)."""
    meta = project_meta(repo)
    tools = discover_tools(repo)
    if rel == "smithery.yaml":
        return _smithery_yaml(meta, tools)
    if rel == "server.json":
        return _server_json(meta)
    if rel == ".well-known/mcp/server-card.json":
        return _server_card(meta, tools)
    if rel == "package.json":
        return _package_json(meta)
    if rel == "glama.json":
        return _glama_json(meta)
    if rel == "SECURITY.md":
        return _security_md(meta)
    raise ValueError(f"not a scaffoldable file: {rel!r}")


def scaffold(repo: Path) -> List[str]:
    """Create every SCAFFOLDABLE file that is currently missing.

    Returns the list of relative paths actually written. Existing files are
    never overwritten. server.py is never touched and no repo code is run.
    """
    repo = Path(repo).resolve()
    written: List[str] = []
    for rel in SCAFFOLDABLE:
        dest = repo / rel
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(render(repo, rel), encoding="utf-8")
        written.append(rel)
    return written

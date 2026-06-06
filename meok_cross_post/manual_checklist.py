"""Manual directory submission checklist.

For directories without a public API (Docker MCP Catalog, Glama, MCPize,
PulseMCP), print a clean markdown checklist the user can work through
manually. Each line has the exact URL and any files to add.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from meok_cross_post.schema import ManualChecklistItem


def render_checklist(repo_name: str, docker_template: Optional[Path] = None) -> str:
    """Render the manual checklist as markdown."""
    items: list[ManualChecklistItem] = [
        ManualChecklistItem(
            directory="Docker MCP Catalog",
            url="https://github.com/docker/mcp-registry/new",
            action=("Fork docker/mcp-registry, add "
                    f"`servers/{repo_name}.yaml`, open PR"),
            template_path=str(docker_template) if docker_template else "",
            notes="~24h SLA. Template generated below; copy it into your fork.",
        ),
        ManualChecklistItem(
            directory="Glama",
            url="https://glama.ai/mcp/servers",
            action="Click 'Add Server' → paste your repo URL",
            template_path="",
            notes=("Your glama.json should already claim CSOAI-ORG as maintainer. "
                   "If not, edit the file in your repo first."),
        ),
        ManualChecklistItem(
            directory="MCPize",
            url="https://mcpize.com/developer/servers/new",
            action=("Open the form, paste repo URL + description. "
                    "Or `npm i -g mcpize && mcpize deploy` from the repo."),
            template_path="",
            notes="Flip visibility to public in the dashboard after deploy.",
        ),
        ManualChecklistItem(
            directory="PulseMCP",
            url="https://www.pulsemcp.com/submit",
            action="One form, ~2 minutes. Paste repo URL + description.",
            template_path="",
            notes="",
        ),
    ]

    lines = [f"=== Manual directory submissions for {repo_name} ===", ""]
    for it in items:
        lines.append(f"[ ] **{it.directory}** — {it.action}")
        lines.append(f"    URL: {it.url}")
        if it.template_path:
            lines.append(f"    Template file: `{it.template_path}`")
        if it.notes:
            lines.append(f"    Note: {it.notes}")
        lines.append("")

    return "\n".join(lines)

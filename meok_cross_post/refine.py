"""Gap-report helper for the `refine` audit→improve→re-audit→gate loop.

Turns a failing ScoreCard into a precise, actionable remediation report:
for every failed/low check it states the check id, what's missing, and the
exact fix. Grouped by category. This codifies the manual remediation loop.
"""

from __future__ import annotations

from typing import Dict, List

from meok_cross_post.schema import CheckStatus, ScoreCard

# Exact remediation per check id. Keep these concrete and copy-pasteable.
REMEDIATION: Dict[str, str] = {
    # A — installability
    "has_pyproject_toml":
        "create pyproject.toml with [build-system] + [project] tables",
    "pyproject_uses_hatchling":
        'set build-system.build-backend = "hatchling.build" (requires = ["hatchling"])',
    "pyproject_only_includes_server_py":
        'add [tool.hatch.build.targets.wheel] with only-include = ["server.py"]',
    "pyproject_declares_mcp_dep":
        'add "mcp>=1.0.0" to [project].dependencies',
    "pyproject_has_entry_point":
        'add [project.scripts] with an entry like `<name> = "server:main"`',
    "wheel_builds_clean":
        "run `python -m build --wheel` and fix what it reports",
    # B — server
    "server_py_imports_clean":
        "fix server.py so `python -c 'import server'` exits 0 (resolve import errors)",
    "server_declares_mcp_object":
        'declare a module-level `mcp = FastMCP(...)` (or `mcp = Server(...)`) in server.py',
    "server_registers_at_least_one_tool":
        "register >= 3 tools with @mcp.tool() decorators in server.py",
    "tool_names_unique_and_snake_case":
        "rename tools so every name is unique and snake_case",
    "all_tools_have_docstring":
        "add a docstring to every @mcp.tool function",
    "has_auth_middleware":
        "add auth_middleware.py (a real tier/auth check, > 100 B)",
    "has_real_test_file":
        "add tests/test_*.py with real assertions (> 500 B)",
    # C — discovery
    "has_smithery_yaml":
        "create smithery.yaml",
    "smithery_yaml_is_declarative":
        "create smithery.yaml with a declarative `tools:` array and NO `runtime:` block",
    "has_server_json":
        "create server.json with the MCP-Registry $schema and a pypi package entry",
    "has_well_known_server_card":
        "create .well-known/mcp/server-card.json",
    "has_glama_json":
        'create glama.json claiming CSOAI-ORG as maintainer',
    "has_package_json":
        'create package.json with mcp.entry = "server:main"',
    # D — distribution
    "has_dockerfile_glama":
        "add Dockerfile.glama (FROM python:3* + reference mcp-wrapper.py)",
    "has_mcp_wrapper":
        "add mcp-wrapper.py: `from server import mcp`, a /.well-known/mcp/server-card.json "
        "route, on streamable-http transport",
    "ghcr_image_public_exists":
        "publish a public GHCR image (network probe — run with --allow-network)",
    "listed_on_smithery":
        "publish to Smithery (network probe — run with --allow-network)",
    "listed_on_mcp_registry":
        "publish to the MCP Registry (network probe — run with --allow-network)",
    # E — ci/cd
    "has_test_workflow":
        "add .github/workflows/test.yml running pytest on the py3.10/3.11 matrix",
    "has_ci_workflow":
        "add .github/workflows/ci.yml",
    "has_smithery_publish_workflow":
        "add .github/workflows/mcp-smithery-publish.yml (@smithery/cli on release)",
    "readme_has_install_features_license":
        "add Install + Features/Usage + License sections to README.md",
    "has_security_md":
        "add SECURITY.md with a security@ contact",
}


def gap_report(sc: ScoreCard) -> str:
    """Render an actionable GAP REPORT for every failed/low check, by category."""
    # Group failing/low checks by category, preserving rubric order.
    by_cat: Dict[str, List[str]] = {}
    for c in sc.checks:
        if c.status in (CheckStatus.FAIL, CheckStatus.WARN):
            fix = REMEDIATION.get(c.id, "(no remediation registered)")
            line = (
                f"  [{c.status.value.upper()}] `{c.id}` "
                f"({c.earned}/{c.points} pts) — {c.evidence}\n"
                f"      FIX: {fix}"
            )
            by_cat.setdefault(c.category, []).append(line)

    lines: List[str] = [f"=== GAP REPORT for {sc.repo_name} "
                        f"({sc.total_points}/{sc.eligible_points}, gate={sc.gate.value}) ==="]
    if not by_cat:
        lines.append("  No failing checks — but the gate is still not MERGE "
                     "(check category minimums / network probes).")
    for cat in sc.category_max:
        if cat in by_cat:
            lines.append("")
            lines.append(f"{cat}:")
            lines.extend(by_cat[cat])

    if sc.warnings:
        lines.append("")
        lines.append("Warnings:")
        for w in sc.warnings:
            lines.append(f"  - {w}")
    return "\n".join(lines)

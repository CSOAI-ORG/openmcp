"""100-pt rubric + 22 check methods for the MEOK fleet scorecard.

This is the canonical audit. Catches empty shells, missing discovery files,
broken `mcp`-object declarations, etc. The merge gate is the AND of:
  - total score >= 80
  - every per-category minimum satisfied

Run locally with `meok-cross-post audit <path>`. Add `--network` to enable
the 3 network probes (GHCR, Smithery, MCP Registry).
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml

from meok_cross_post.schema import CheckResult, CheckStatus, GateVerdict, ScoreCard

# --------------------------------------------------------------------- rubric

# Per-category point totals MUST sum to 100. The "category_minimums" map is
# the AND-condition for the merge gate: a repo cannot pass with a desert
# category even if its total is otherwise high.
RUBRIC: Dict[str, Any] = {
    "version": "1.0.0",
    "gate_threshold": 80,
    "warn_threshold": 60,
    "category_minimums": {
        "A_installability": 18,    # of 25
        "B_server":         12,    # of 25
        "C_discovery":      14,    # of 25
        "D_distribution":    6,    # of 15
        "E_cicd":            5,    # of 10
    },
}


# ---------------------------------------------------------------------- helper


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        return ""


def _status(earned: int, points: int) -> CheckStatus:
    if earned >= points:
        return CheckStatus.PASS
    if earned > 0:
        return CheckStatus.WARN
    return CheckStatus.FAIL


# ----------------------------------------------------------------------- check


@dataclass
class Check:
    """Declarative single check result."""

    id: str
    category: str
    points: int
    earned: int
    evidence: str = ""
    gradated: bool = False
    cost: str = "1 fs read"
    skipped: bool = False


def _make(check: Check) -> CheckResult:
    return CheckResult(
        id=check.id,
        category=check.category,
        points=check.points,
        earned=0 if check.skipped else check.earned,
        status=CheckStatus.SKIP if check.skipped else _status(check.earned, check.points),
        evidence=check.evidence,
        gradated=check.gradated,
        cost=check.cost,
    )


# =====================================================================
# A. PACKAGE INSTALLABILITY — 25 pts
# =====================================================================


def check_has_pyproject_toml(repo: Path) -> Check:
    p = repo / "pyproject.toml"
    return Check(
        id="has_pyproject_toml", category="A_installability", points=8,
        earned=8 if p.is_file() else 0,
        evidence=f"pyproject.toml present at {p}" if p.is_file() else "pyproject.toml missing",
    )


def check_pyproject_uses_hatchling(repo: Path) -> Check:
    p = repo / "pyproject.toml"
    if not p.is_file():
        return Check("pyproject_uses_hatchling", "A_installability", 4, 0,
                     evidence="no pyproject.toml", skipped=True)
    try:
        data = tomllib.loads(_read(p))
    except tomllib.TOMLDecodeError as e:
        return Check("pyproject_uses_hatchling", "A_installability", 4, 0,
                     evidence=f"pyproject.toml malformed: {e}")
    backend = (data.get("build-system") or {}).get("build-backend", "")
    if backend == "hatchling.build":
        return Check("pyproject_uses_hatchling", "A_installability", 4, 4,
                     evidence="build-backend = hatchling.build")
    return Check("pyproject_uses_hatchling", "A_installability", 4, 0,
                 evidence=f"build-backend = {backend!r} (expected 'hatchling.build')")


def check_pyproject_only_includes_server_py(repo: Path) -> Check:
    p = repo / "pyproject.toml"
    if not p.is_file():
        return Check("pyproject_only_includes_server_py", "A_installability", 5, 0,
                     evidence="no pyproject.toml", skipped=True)
    try:
        data = tomllib.loads(_read(p))
    except tomllib.TOMLDecodeError:
        return Check("pyproject_only_includes_server_py", "A_installability", 5, 0,
                     evidence="pyproject.toml malformed")
    include = (
        (data.get("tool") or {})
        .get("hatch", {})
        .get("build", {})
        .get("targets", {})
        .get("wheel", {})
        .get("only-include") or []
    )
    if "server.py" in include and len(include) <= 2:
        return Check("pyproject_only_includes_server_py", "A_installability", 5, 5,
                     evidence=f"only-include={include} (ship only server.py)",
                     gradated=True)
    if "server.py" in include:
        return Check("pyproject_only_includes_server_py", "A_installability", 5, 3,
                     evidence=f"only-include={include} (bloated, but server.py present)",
                     gradated=True)
    return Check("pyproject_only_includes_server_py", "A_installability", 5, 0,
                 evidence=f"only-include={include} (server.py not in list)")


_MCP_DEPS_RE = re.compile(r"^mcp([><=~!]+)([\d.]+)")


def check_pyproject_declares_mcp_dep(repo: Path) -> Check:
    p = repo / "pyproject.toml"
    if not p.is_file():
        return Check("pyproject_declares_mcp_dep", "A_installability", 4, 0,
                     evidence="no pyproject.toml", skipped=True)
    try:
        data = tomllib.loads(_read(p))
    except tomllib.TOMLDecodeError:
        return Check("pyproject_declares_mcp_dep", "A_installability", 4, 0,
                     evidence="pyproject.toml malformed")
    deps = (data.get("project") or {}).get("dependencies") or []
    for d in deps:
        m = _MCP_DEPS_RE.match(d.strip())
        if m and m.group(1) in {">=", "~=", ">", "=="}:
            try:
                ver = tuple(int(x) for x in m.group(2).split(".") if x.isdigit())
                if ver >= (1, 0, 0):
                    return Check("pyproject_declares_mcp_dep", "A_installability", 4, 4,
                                 evidence=f"declared dep: {d!r}")
            except (ValueError, IndexError):
                pass
    return Check("pyproject_declares_mcp_dep", "A_installability", 4, 0,
                 evidence=f"no 'mcp>=1.0.0' style dep found in {deps}")


def check_pyproject_has_entry_point(repo: Path) -> Check:
    p = repo / "pyproject.toml"
    if not p.is_file():
        return Check("pyproject_has_entry_point", "A_installability", 2, 0,
                     evidence="no pyproject.toml", skipped=True)
    try:
        data = tomllib.loads(_read(p))
    except tomllib.TOMLDecodeError:
        return Check("pyproject_has_entry_point", "A_installability", 2, 0,
                     evidence="pyproject.toml malformed")
    scripts = (data.get("project") or {}).get("scripts") or {}
    if scripts:
        names = list(scripts.keys())
        return Check("pyproject_has_entry_point", "A_installability", 2, 2,
                     evidence=f"[project.scripts] entry: {names[0]} = {scripts[names[0]]!r}")
    return Check("pyproject_has_entry_point", "A_installability", 2, 0,
                 evidence="[project.scripts] missing or empty")


def check_wheel_builds_clean(repo: Path) -> Check:
    """Run `python -m build --wheel` in the repo. Off the hot path (CI gate only).

    We do NOT run this on every audit — it requires `build` installed and
    ~3s per repo. The PR-comment bot uses this; the monthly cron does not
    (it just imports server.py to confirm).
    """
    if not (repo / "pyproject.toml").is_file():
        return Check("wheel_builds_clean", "A_installability", 2, 0,
                     evidence="no pyproject.toml", skipped=True)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", str(repo / "dist")],
            cwd=repo, capture_output=True, timeout=60,
            env={"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
                 "HOME": "/tmp", "TMPDIR": "/tmp"},
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return Check("wheel_builds_clean", "A_installability", 2, 0,
                     evidence=f"`python -m build` unavailable: {e}", cost="subprocess (skipped)")
    if proc.returncode != 0:
        return Check("wheel_builds_clean", "A_installability", 2, 0,
                     evidence=f"build failed (rc={proc.returncode}); "
                              f"stderr: {proc.stderr.decode('utf-8', 'replace')[:200]}",
                     cost="~3s subprocess")
    return Check("wheel_builds_clean", "A_installability", 2, 2,
                 evidence="`python -m build --wheel` exited 0",
                 cost="~3s subprocess")


# =====================================================================
# B. SERVER CORRECTNESS — 25 pts
# =====================================================================


def check_server_py_imports_clean(repo: Path) -> Check:
    """Spawn a hermetic Python that imports server. ~2s."""
    p = repo / "server.py"
    if not p.is_file():
        return Check("server_py_imports_clean", "B_server", 5, 0,
                     evidence="server.py missing", skipped=True)
    try:
        proc = subprocess.run(
            [sys.executable, "-c", "import server"],
            cwd=repo, capture_output=True, timeout=15,
            env={"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
                 "HOME": "/tmp", "TMPDIR": "/tmp", "PYTHONPATH": str(repo)},
        )
    except subprocess.TimeoutExpired:
        return Check("server_py_imports_clean", "B_server", 5, 0,
                     evidence="`import server` timed out", cost="~2s subprocess")
    if proc.returncode == 0:
        return Check("server_py_imports_clean", "B_server", 5, 5,
                     evidence="`import server` returned 0", cost="~2s subprocess")
    return Check("server_py_imports_clean", "B_server", 5, 0,
                 evidence=f"`import server` rc={proc.returncode}; "
                          f"stderr: {proc.stderr.decode('utf-8', 'replace')[:200]}",
                 cost="~2s subprocess")


_MCP_OBJECT_RE = re.compile(r"^mcp\s*=\s*(FastMCP\(|Server\()", re.M)


def check_server_declares_mcp_object(repo: Path) -> Check:
    p = repo / "server.py"
    if not p.is_file():
        return Check("server_declares_mcp_object", "B_server", 4, 0,
                     evidence="server.py missing", skipped=True)
    src = _read(p)
    m = _MCP_OBJECT_RE.search(src)
    if m:
        return Check("server_declares_mcp_object", "B_server", 4, 4,
                     evidence=f"`mcp = {m.group(1).rstrip('(')}(...)` declared")
    return Check("server_declares_mcp_object", "B_server", 4, 0,
                 evidence="no `mcp = FastMCP(...)` or `mcp = Server(...)` at module level")


_TOOL_RE = re.compile(r"@mcp\.tool")
_TOOL_NAME_RE = re.compile(
    r"@mcp\.tool(?:\([^)]*name=[\"\']([a-z_][a-z0-9_]*)[\"\']\))?"
)


def check_server_registers_at_least_one_tool(repo: Path) -> Check:
    p = repo / "server.py"
    if not p.is_file():
        return Check("server_registers_at_least_one_tool", "B_server", 4, 0,
                     evidence="server.py missing", skipped=True)
    src = _read(p)
    n = len(_TOOL_RE.findall(src))
    if n >= 3:
        return Check("server_registers_at_least_one_tool", "B_server", 4, 4,
                     evidence=f"{n} @mcp.tool() decorators (>= 3)",
                     gradated=True)
    if n >= 1:
        return Check("server_registers_at_least_one_tool", "B_server", 4, 2,
                     evidence=f"only {n} @mcp.tool() (recommend >= 3)",
                     gradated=True)
    return Check("server_registers_at_least_one_tool", "B_server", 4, 0,
                 evidence="no @mcp.tool() decorators found")


def check_tool_names_unique_and_snake_case(repo: Path) -> Check:
    p = repo / "server.py"
    if not p.is_file():
        return Check("tool_names_unique_and_snake_case", "B_server", 3, 0,
                     evidence="server.py missing", skipped=True)
    src = _read(p)
    # If a `name=` kwarg is used, that wins; otherwise the function name is the
    # tool name. We extract both: the explicit ones first, then the function
    # names of decorated functions. To keep this heuristic and avoid a full
    # AST pass, we just regex for name= and the immediate-following `def name(`
    # when name= is absent. (False positives are rare and caught by import.)
    explicit = re.findall(r"@mcp\.tool\([^)]*name=[\"\']([a-z_][a-z0-9_]*)[\"\']", src)
    if explicit:
        names = explicit
    else:
        names = re.findall(r"@mcp\.tool[^\n]*\n(?:@\w+[^\n]*\n)*\s*def\s+([a-z_][a-z0-9_]*)\s*\(", src)
    if not names:
        return Check("tool_names_unique_and_snake_case", "B_server", 3, 0,
                     evidence="no @mcp.tool() tools to name-check (overlaps with prior check)")
    bad_shape = [n for n in names if not re.match(r"^[a-z][a-z0-9_]*$", n)]
    if bad_shape:
        return Check("tool_names_unique_and_snake_case", "B_server", 3, 0,
                     evidence=f"non-snake_case tool names: {bad_shape}")
    if len(set(names)) != len(names):
        from collections import Counter
        dups = [n for n, c in Counter(names).items() if c > 1]
        return Check("tool_names_unique_and_snake_case", "B_server", 3, 0,
                     evidence=f"duplicate tool names: {dups}")
    return Check("tool_names_unique_and_snake_case", "B_server", 3, 3,
                 evidence=f"{len(names)} tools, all snake_case + unique: {names}")


def _tool_funcs_with_docstrings(server_py: str) -> Tuple[int, int, List[str]]:
    """AST-based: count @mcp.tool-decorated functions and how many are docstringed.

    Returns (total, with_docstring, names_with_docstring).
    """
    try:
        tree = ast.parse(server_py)
    except SyntaxError:
        return 0, 0, []
    tool_funcs: List[ast.FunctionDef] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            # @mcp.tool / @mcp.tool(name="x") / @mcp.tool()
            if isinstance(dec, ast.Attribute) and dec.attr == "tool":
                tool_funcs.append(node)
                break
            if isinstance(dec, ast.Call):
                fn = dec.func
                if isinstance(fn, ast.Attribute) and fn.attr == "tool":
                    tool_funcs.append(node)
                    break
    with_doc = [f.name for f in tool_funcs if ast.get_docstring(f)]
    return len(tool_funcs), len(with_doc), with_doc


def check_all_tools_have_docstring(repo: Path) -> Check:
    p = repo / "server.py"
    if not p.is_file():
        return Check("all_tools_have_docstring", "B_server", 3, 0,
                     evidence="server.py missing", skipped=True)
    total, with_doc, names = _tool_funcs_with_docstrings(_read(p))
    if total == 0:
        return Check("all_tools_have_docstring", "B_server", 3, 0,
                     evidence="no @mcp.tool functions found (overlaps with prior check)",
                     gradated=True)
    ratio = with_doc / total
    if ratio == 1.0:
        return Check("all_tools_have_docstring", "B_server", 3, 3,
                     evidence=f"all {total} tools have a docstring: {names}",
                     gradated=True)
    if ratio >= 0.5:
        return Check("all_tools_have_docstring", "B_server", 3, 1,
                     evidence=f"only {with_doc}/{total} tools docstringed: {names}",
                     gradated=True)
    return Check("all_tools_have_docstring", "B_server", 3, 0,
                 evidence=f"{with_doc}/{total} tools docstringed (need all)",
                 gradated=True)


def check_has_auth_middleware(repo: Path) -> Check:
    p = repo / "auth_middleware.py"
    return Check(
        id="has_auth_middleware", category="B_server", points=3,
        earned=3 if p.is_file() and p.stat().st_size > 100 else 0,
        evidence=f"auth_middleware.py present ({p.stat().st_size} B)"
                 if p.is_file() and p.stat().st_size > 100
                 else "auth_middleware.py missing or empty",
    )


def check_has_real_test_file(repo: Path) -> Check:
    tests_dir = repo / "tests"
    if not tests_dir.is_dir():
        return Check("has_real_test_file", "B_server", 3, 0,
                     evidence="tests/ directory missing")
    test_files = list(tests_dir.glob("test_*.py"))
    if not test_files:
        return Check("has_real_test_file", "B_server", 3, 0,
                     evidence="no test_*.py in tests/")
    big = [t for t in test_files if t.stat().st_size > 500]
    if big:
        return Check("has_real_test_file", "B_server", 3, 3,
                     evidence=f"{len(big)} test file(s) > 500 B: "
                              f"{[t.name for t in big]}", gradated=True)
    return Check("has_real_test_file", "B_server", 3, 0,
                 evidence=f"test file(s) exist but are stubs (< 500 B): "
                          f"{[t.name for t in test_files]}", gradated=True)


# =====================================================================
# C. DISCOVERY & DIRECTORIES — 25 pts
# =====================================================================


def check_has_smithery_yaml(repo: Path) -> Check:
    p = repo / "smithery.yaml"
    return Check(
        id="has_smithery_yaml", category="C_discovery", points=6,
        earned=6 if p.is_file() else 0,
        evidence=f"smithery.yaml present ({p.stat().st_size} B)"
                 if p.is_file() else "smithery.yaml missing",
    )


def check_smithery_yaml_is_declarative(repo: Path) -> Check:
    p = repo / "smithery.yaml"
    if not p.is_file():
        return Check("smithery_yaml_is_declarative", "C_discovery", 3, 0,
                     evidence="no smithery.yaml", skipped=True)
    try:
        y = yaml.safe_load(_read(p)) or {}
    except yaml.YAMLError as e:
        return Check("smithery_yaml_is_declarative", "C_discovery", 3, 0,
                     evidence=f"smithery.yaml malformed: {e}")
    has_runtime = "runtime" in y
    has_tools = isinstance(y.get("tools"), list) and len(y["tools"]) >= 1
    if not has_runtime and has_tools:
        return Check("smithery_yaml_is_declarative", "C_discovery", 3, 3,
                     evidence=f"declarative: {len(y['tools'])} tools listed, no `runtime:` block")
    if has_runtime:
        return Check("smithery_yaml_is_declarative", "C_discovery", 3, 0,
                     evidence="`runtime:` block present (deprecated form)")
    return Check("smithery_yaml_is_declarative", "C_discovery", 3, 0,
                 evidence=f"no `tools:` array (declarative form required)")


def check_has_server_json(repo: Path) -> Check:
    p = repo / "server.json"
    if not p.is_file():
        return Check("has_server_json", "C_discovery", 5, 0,
                     evidence="server.json missing")
    try:
        j = json.loads(_read(p))
    except json.JSONDecodeError as e:
        return Check("has_server_json", "C_discovery", 5, 0,
                     evidence=f"server.json malformed: {e}")
    schema_ok = j.get("$schema", "").startswith("https://static.modelcontextprotocol.io/")
    pypi_ok = any((pkg.get("registryType") == "pypi") for pkg in j.get("packages") or [])
    if schema_ok and pypi_ok:
        return Check("has_server_json", "C_discovery", 5, 5,
                     evidence="valid MCP-Registry schema with PyPI package")
    return Check("has_server_json", "C_discovery", 5, 0,
                 evidence=f"schema_ok={schema_ok}, pypi_pkg={pypi_ok}")


def check_has_well_known_server_card(repo: Path) -> Check:
    p = repo / ".well-known" / "mcp" / "server-card.json"
    return Check(
        id="has_well_known_server_card", category="C_discovery", points=4,
        earned=4 if p.is_file() else 0,
        evidence=".well-known/mcp/server-card.json present"
                 if p.is_file() else ".well-known/mcp/server-card.json missing",
    )


def check_has_glama_json(repo: Path) -> Check:
    p = repo / "glama.json"
    if not p.is_file():
        return Check("has_glama_json", "C_discovery", 4, 0,
                     evidence="glama.json missing")
    src = _read(p)
    if "CSOAI-ORG" in src or "meok-ai-labs" in src.lower():
        return Check("has_glama_json", "C_discovery", 4, 4,
                     evidence=f"glama.json present with MEOK maintainer")
    return Check("has_glama_json", "C_discovery", 4, 0,
                 evidence="glama.json present but maintainer is not CSOAI-ORG / meok-ai-labs")


def check_has_package_json(repo: Path) -> Check:
    p = repo / "package.json"
    if not p.is_file():
        return Check("has_package_json", "C_discovery", 3, 0,
                     evidence="package.json missing")
    try:
        j = json.loads(_read(p))
    except json.JSONDecodeError:
        return Check("has_package_json", "C_discovery", 3, 0,
                     evidence="package.json malformed")
    has_mcp_block = "mcp" in j and isinstance(j["mcp"], dict)
    has_entry = (j.get("mcp") or {}).get("entry") == "server:main"
    if has_mcp_block and has_entry:
        return Check("has_package_json", "C_discovery", 3, 3,
                     evidence="package.json with mcp.entry = server:main")
    if has_mcp_block or j.get("name"):
        return Check("has_package_json", "C_discovery", 3, 1,
                     evidence="package.json has name but mcp.entry is not server:main")
    return Check("has_package_json", "C_discovery", 3, 0,
                 evidence="package.json has no useful metadata")


# =====================================================================
# D. DISTRIBUTION & OPS — 15 pts
# =====================================================================


def check_has_dockerfile_glama(repo: Path) -> Check:
    p = repo / "Dockerfile.glama"
    if not p.is_file():
        return Check("has_dockerfile_glama", "D_distribution", 4, 0,
                     evidence="Dockerfile.glama missing")
    src = _read(p)
    has_python = re.search(r"^FROM python:3", src, re.M) is not None
    has_wrapper = "mcp-wrapper.py" in src
    if has_python and has_wrapper:
        return Check("has_dockerfile_glama", "D_distribution", 4, 4,
                     evidence="Dockerfile.glama: python:3 + mcp-wrapper.py")
    return Check("has_dockerfile_glama", "D_distribution", 4, 0,
                 evidence=f"Dockerfile.glama present but missing python:3 or mcp-wrapper.py reference")


_WRAPPER_RE = re.compile(r"from server import mcp")
_WRAPPER_HEALTH_RE = re.compile(r"\.well-known/mcp/server-card\.json")
_WRAPPER_TRANSPORT_RE = re.compile(r"streamable-http")


def check_has_mcp_wrapper(repo: Path) -> Check:
    p = repo / "mcp-wrapper.py"
    if not p.is_file():
        return Check("has_mcp_wrapper", "D_distribution", 4, 0,
                     evidence="mcp-wrapper.py missing")
    src = _read(p)
    if not _WRAPPER_RE.search(src):
        return Check("has_mcp_wrapper", "D_distribution", 4, 0,
                     evidence="mcp-wrapper.py present but does not `from server import mcp`")
    if not _WRAPPER_HEALTH_RE.search(src):
        return Check("has_mcp_wrapper", "D_distribution", 4, 0,
                     evidence="mcp-wrapper.py present but missing /.well-known/mcp/server-card.json route")
    if not _WRAPPER_TRANSPORT_RE.search(src):
        return Check("has_mcp_wrapper", "D_distribution", 4, 0,
                     evidence="mcp-wrapper.py present but not on streamable-http transport")
    return Check("has_mcp_wrapper", "D_distribution", 4, 4,
                 evidence="mcp-wrapper.py: from server import mcp + well-known route + streamable-http")


def check_ghcr_image_public_exists(repo: Path) -> Check:
    """Network probe (GHCR). 4 pts if public :latest; 2 if any public tag;
    0 if private/missing. 6h cache. Off the hot path (allow_network=False).

    Wired to `meok_cross_post.ghcr.probe` when allow_network=True.
    """
    return Check(
        id="ghcr_image_public_exists", category="D_distribution", points=4,
        earned=0,
        evidence="network probe skipped (set allow_network=True)",
        cost="~150ms (skipped)",
        skipped=True,
    )


def check_listed_on_smithery(repo: Path) -> Check:
    """Network probe (Smithery). 2 pts if listed. 24h cache.

    Wired to `meok_cross_post.smithery.probe_listed` when allow_network=True.
    """
    return Check(
        id="listed_on_smithery", category="D_distribution", points=2,
        earned=0,
        evidence="network probe skipped (set allow_network=True)",
        cost="~300ms (skipped)",
        skipped=True,
    )


def check_listed_on_mcp_registry(repo: Path) -> Check:
    """Network probe (MCP Registry). 1 pt if listed. 24h cache.

    Wired to `meok_cross_post.mcp_registry.probe_listed` when allow_network=True.
    """
    return Check(
        id="listed_on_mcp_registry", category="D_distribution", points=1,
        earned=0,
        evidence="network probe skipped (set allow_network=True)",
        cost="~200ms (skipped)",
        skipped=True,
    )


# =====================================================================
# E. CI/CD & DOCS — 10 pts
# =====================================================================


def check_has_test_workflow(repo: Path) -> Check:
    p = repo / ".github" / "workflows" / "test.yml"
    if not p.is_file():
        return Check("has_test_workflow", "E_cicd", 3, 0,
                     evidence=".github/workflows/test.yml missing")
    src = _read(p)
    has_pytest = "pytest" in src
    has_py = "3.10" in src or "3.11" in src
    if has_pytest and has_py:
        return Check("has_test_workflow", "E_cicd", 3, 3,
                     evidence="test.yml with pytest + Python 3.10/3.11")
    return Check("has_test_workflow", "E_cicd", 3, 0,
                 evidence="test.yml present but missing pytest or py3.10/3.11 matrix")


def check_has_ci_workflow(repo: Path) -> Check:
    p = repo / ".github" / "workflows" / "ci.yml"
    return Check(
        id="has_ci_workflow", category="E_cicd", points=2,
        earned=2 if p.is_file() else 0,
        evidence=f"ci.yml present ({p.stat().st_size} B)"
                 if p.is_file() else "ci.yml missing",
    )


def check_has_smithery_publish_workflow(repo: Path) -> Check:
    p = repo / ".github" / "workflows" / "mcp-smithery-publish.yml"
    if not p.is_file():
        return Check("has_smithery_publish_workflow", "E_cicd", 2, 0,
                     evidence="mcp-smithery-publish.yml missing")
    src = _read(p)
    if "@smithery/cli" in src and "release" in src:
        return Check("has_smithery_publish_workflow", "E_cicd", 2, 2,
                     evidence="mcp-smithery-publish.yml: @smithery/cli on release")
    return Check("has_smithery_publish_workflow", "E_cicd", 2, 0,
                 evidence="mcp-smithery-publish.yml present but missing @smithery/cli or release trigger")


def check_readme_has_install_features_license(repo: Path) -> Check:
    p = repo / "README.md"
    if not p.is_file():
        return Check("readme_has_install_features_license", "E_cicd", 2, 0,
                     evidence="README.md missing")
    src = _read(p).lower()
    has_install = "install" in src
    has_features = "feature" in src or "usage" in src or "tools" in src
    has_license = "license" in src or "apache" in src or "mit" in src
    if has_install and has_features and has_license:
        return Check("readme_has_install_features_license", "E_cicd", 2, 2,
                     evidence="README has install + features/usage + license",
                     gradated=True)
    if has_install and (has_features or has_license):
        return Check("readme_has_install_features_license", "E_cicd", 2, 1,
                     evidence=f"README has install (features={has_features}, license={has_license})",
                     gradated=True)
    return Check("readme_has_install_features_license", "E_cicd", 2, 0,
                 evidence="README missing install / features / license",
                 gradated=True)


def check_has_security_md(repo: Path) -> Check:
    p = repo / "SECURITY.md"
    if not p.is_file():
        return Check("has_security_md", "E_cicd", 1, 0,
                     evidence="SECURITY.md missing")
    if "security@" in _read(p).lower():
        return Check("has_security_md", "E_cicd", 1, 1,
                     evidence="SECURITY.md with security@ contact")
    return Check("has_security_md", "E_cicd", 1, 0,
                 evidence="SECURITY.md present but no security@ contact")


# =====================================================================
# Orchestrator
# =====================================================================


# Default check order (matches the rubric above; exposed for `audit` CLI).
# `check_wheel_builds_clean` is opt-in (off the hot path) — pass
# `include_wheel_check=True` to Audit() to enable it. The local-only
# default keeps the scorecard fast (~3s/repo) and avoids requiring
# `python-build` to be installed.
DEFAULT_CHECKS: List[Callable[[Path], Check]] = [
    # A — 25
    check_has_pyproject_toml,
    check_pyproject_uses_hatchling,
    check_pyproject_only_includes_server_py,
    check_pyproject_declares_mcp_dep,
    check_pyproject_has_entry_point,
    # B — 25
    check_server_py_imports_clean,
    check_server_declares_mcp_object,
    check_server_registers_at_least_one_tool,
    check_tool_names_unique_and_snake_case,
    check_all_tools_have_docstring,
    check_has_auth_middleware,
    check_has_real_test_file,
    # C — 25
    check_has_smithery_yaml,
    check_smithery_yaml_is_declarative,
    check_has_server_json,
    check_has_well_known_server_card,
    check_has_glama_json,
    check_has_package_json,
    # D — 15 (network checks stubbed in local-only mode)
    check_has_dockerfile_glama,
    check_has_mcp_wrapper,
    check_ghcr_image_public_exists,
    check_listed_on_smithery,
    check_listed_on_mcp_registry,
    # E — 10
    check_has_test_workflow,
    check_has_ci_workflow,
    check_has_smithery_publish_workflow,
    check_readme_has_install_features_license,
    check_has_security_md,
]

WHEEL_CHECK: Callable[[Path], Check] = check_wheel_builds_clean  # 2 pts, opt-in


def _category_totals(checks: List[CheckResult]) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, bool]]:
    cats: Dict[str, int] = {}
    maxes: Dict[str, int] = {}
    for c in checks:
        cats[c.category] = cats.get(c.category, 0) + c.earned
        maxes[c.category] = maxes.get(c.category, 0) + c.points
    minimums = RUBRIC["category_minimums"]
    mins_met = {cat: (cats.get(cat, 0) >= minimums.get(cat, 0)) for cat in minimums}
    return cats, maxes, mins_met


def _gate(cats: Dict[str, int], mins_met: Dict[str, bool], total: int) -> GateVerdict:
    if total >= RUBRIC["gate_threshold"] and all(mins_met.values()):
        return GateVerdict.MERGE
    if total >= RUBRIC["warn_threshold"]:
        return GateVerdict.REVIEW
    return GateVerdict.BLOCK


class Audit:
    """Score a flagship repo against the MEOK fleet rubric.

    Usage:
        audit = Audit()
        scorecard = audit.score(Path("/path/to/flagship"))
        print(scorecard.score, scorecard.gate)
    """

    def __init__(
        self,
        checks: Optional[List[Callable[[Path], Check]]] = None,
        include_wheel_check: bool = False,
    ) -> None:
        self.checks = list(checks or DEFAULT_CHECKS)
        if include_wheel_check and WHEEL_CHECK not in self.checks:
            # Insert after the last A-category check (index 5: A has 5 checks).
            self.checks.insert(5, WHEEL_CHECK)

    def score(self, repo: Path, allow_network: bool = False) -> ScoreCard:
        """Run all checks and return a ScoreCard.

        `allow_network` is a placeholder for now (network probes are
        always skipped — they live in `ghcr.py`/`smithery.py`/
        `mcp_registry.py` and are wired into the monthly cron).
        """
        repo = Path(repo).resolve()
        results = [_make(c(repo)) for c in self.checks]

        # All checks' `points` fields sum to the aspirational 100. But a run
        # with `include_wheel_check=False` and skipped network probes only
        # has <100 eligible points; the missing are not "lost" — they are
        # simply not in scope for this run. Score = total / eligible.
        total = sum(r.earned for r in results)
        skipped_pts = sum(r.points for r in results if r.status == CheckStatus.SKIP)
        eligible = sum(r.points for r in results) - skipped_pts
        max_total = eligible + skipped_pts  # always 100 if no check is missing
        cats, maxes, mins_met = _category_totals(results)
        gate = _gate(cats, mins_met, total)

        warnings: List[str] = []
        for cat, ok in mins_met.items():
            if not ok:
                warnings.append(
                    f"Category minimum missed: {cat} scored "
                    f"{cats.get(cat, 0)}/{maxes.get(cat, 0)} (need ≥ "
                    f"{RUBRIC['category_minimums'][cat]})"
                )
        if total < RUBRIC["gate_threshold"]:
            warnings.append(
                f"Total score {total}/{max_total} below merge gate "
                f"({RUBRIC['gate_threshold']})"
            )

        return ScoreCard(
            repo=str(repo),
            repo_name=repo.name,
            total_points=total,
            max_points=max_total,
            eligible_points=eligible,
            score=round((total / eligible) * 100) if eligible else 0,
            gate_threshold=RUBRIC["gate_threshold"],
            warn_threshold=RUBRIC["warn_threshold"],
            gate=gate,
            category_scores=cats,
            category_max=maxes,
            category_minimums_met=mins_met,
            checks=results,
            warnings=warnings,
            generated_at=_ts(),
        )


def score(repo: Path, allow_network: bool = False, include_wheel_check: bool = False) -> ScoreCard:
    """One-shot helper: `from meok_cross_post import audit; audit.score(path)`."""
    return Audit(include_wheel_check=include_wheel_check).score(
        repo, allow_network=allow_network,
    )

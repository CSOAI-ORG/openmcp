"""22 unit tests for the audit rubric, one per check.

These tests use a synthetic `tmp_path`-style fixture so we don't have
to rely on the gold_standard/empty_shell symlinks (which may not exist
in CI). The integration tests at the bottom cover the orchestrator.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from meok_cross_post.audit import (
    Audit,
    check_all_tools_have_docstring,
    check_has_auth_middleware,
    check_has_ci_workflow,
    check_has_dockerfile_glama,
    check_has_glama_json,
    check_has_mcp_wrapper,
    check_has_package_json,
    check_has_pyproject_toml,
    check_has_real_test_file,
    check_has_security_md,
    check_has_server_json,
    check_has_smithery_publish_workflow,
    check_has_smithery_yaml,
    check_has_test_workflow,
    check_has_well_known_server_card,
    check_pyproject_declares_mcp_dep,
    check_pyproject_has_entry_point,
    check_pyproject_only_includes_server_py,
    check_pyproject_uses_hatchling,
    check_readme_has_install_features_license,
    check_server_declares_mcp_object,
    check_server_py_imports_clean,
    check_server_registers_at_least_one_tool,
    check_smithery_yaml_is_declarative,
    check_tool_names_unique_and_snake_case,
)
from meok_cross_post.schema import CheckStatus, GateVerdict


# --------------------------------------------------------------------- helpers


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _good_pyproject() -> str:
    return (
        "[build-system]\n"
        'requires = ["hatchling"]\n'
        'build-backend = "hatchling.build"\n'
        "\n"
        "[project]\n"
        'name = "fake-flagship"\n'
        'version = "0.1.0"\n'
        'dependencies = ["mcp>=1.0.0"]\n'
        "\n"
        "[project.scripts]\n"
        'fake_mcp = "server:main"\n'
        "\n"
        "[tool.hatch.build.targets.wheel]\n"
        'only-include = ["server.py"]\n'
        "\n"
        "[tool.pytest.ini_options]\n"
        'testpaths = ["tests"]\n'
    )


def _good_server_py() -> str:
    # Module-level code, no leading whitespace.
    return (
        '"""A flagship server."""\n'
        "\n"
        "from mcp.server.fastmcp import FastMCP\n"
        "\n"
        'mcp = FastMCP("fake-flagship")\n'
        "\n"
        "@mcp.tool()\n"
        "def cve_lookup(cve_id: str) -> dict:\n"
        '    """Look up a CVE."""\n'
        '    return {"cve": cve_id}\n'
        "\n"
        "@mcp.tool()\n"
        "def severity_routing(cve_ids: list) -> dict:\n"
        '    """Route by severity."""\n'
        "    return {}\n"
        "\n"
        "@mcp.tool()\n"
        'def cve_list_recent(severity: str = "HIGH") -> dict:\n'
        '    """List recent CVEs."""\n'
        "    return {}\n"
    )


def _good_smithery_yaml() -> str:
    return textwrap.dedent("""\
        name: fake-flagship
        description: Test
        version: 0.1.0
        tools:
          - name: cve_lookup
            description: Look up a CVE
            parameters:
              - name: cve_id
                type: string
                required: true
        """)


def _good_server_json() -> str:
    return json.dumps({
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        "name": "CSOAI-ORG/fake-flagship-mcp",
        "version": "0.1.0",
        "description": "Test",
        "packages": [
            {"registryType": "pypi", "identifier": "fake-flagship-mcp",
             "version": "0.1.0", "runtimeHint": "python",
             "transport": {"type": "stdio"}},
        ],
    })


def _good_server_card() -> str:
    return json.dumps({"name": "fake-flagship", "description": "Test"})


def _good_glama_json() -> str:
    return json.dumps({
        "$schema": "https://glama.ai/mcp/schemas/server.json",
        "maintainers": ["CSOAI-ORG"],
    })


def _good_package_json() -> str:
    return json.dumps({
        "name": "@meok-ai-labs/fake-flagship-mcp",
        "version": "0.1.0",
        "mcp": {"name": "fake-flagship-mcp", "entry": "server:main"},
    })


def _good_dockerfile() -> str:
    return textwrap.dedent("""\
        FROM python:3.14-slim
        COPY mcp-wrapper.py /app/mcp-wrapper.py
        CMD ["python", "mcp-wrapper.py"]
        """)


def _good_wrapper() -> str:
    return textwrap.dedent('''\
        from server import mcp

        @mcp.custom_route("/.well-known/mcp/server-card.json", methods=["GET"])
        async def card(_request):
            return {}

        if __name__ == "__main__":
            mcp.settings.host = "0.0.0.0"
            mcp.run(transport="streamable-http")
        ''')


def _good_test_workflow() -> str:
    return textwrap.dedent("""\
        name: Test
        on: [push]
        jobs:
          test:
            runs-on: ubuntu-latest
            strategy:
              matrix:
                python-version: ["3.10", "3.11"]
            steps:
              - uses: actions/checkout@v4
              - uses: actions/setup-python@v5
                with: {python-version: ${{ matrix.python-version }}}
              - run: pip install pytest mcp>=1.0.0
              - run: pytest tests/
        """)


def _good_ci_workflow() -> str:
    return "name: CI\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo\n"


def _good_publish_workflow() -> str:
    return textwrap.dedent("""\
        name: Publish
        on:
          release:
            types: [published]
        jobs:
          publish:
            runs-on: ubuntu-latest
            steps:
              - run: npx @smithery/cli mcp publish
        """)


def _good_readme() -> str:
    return textwrap.dedent("""\
        # fake-flagship

        ## Install
        `pip install fake-flagship-mcp`

        ## Features
        - CVE lookup
        - Severity routing

        ## License
        Apache-2.0
        """)


def _good_security_md() -> str:
    return "Report security issues to security@meok.ai.\n"


@pytest.fixture
def good_repo(tmp_path: Path) -> Path:
    """A repo that should pass every local check (except network probes)."""
    _write(tmp_path / "pyproject.toml", _good_pyproject())
    _write(tmp_path / "server.py", _good_server_py())
    _write(tmp_path / "smithery.yaml", _good_smithery_yaml())
    _write(tmp_path / "server.json", _good_server_json())
    _write(tmp_path / ".well-known" / "mcp" / "server-card.json", _good_server_card())
    _write(tmp_path / "glama.json", _good_glama_json())
    _write(tmp_path / "package.json", _good_package_json())
    _write(tmp_path / "Dockerfile.glama", _good_dockerfile())
    _write(tmp_path / "mcp-wrapper.py", _good_wrapper())
    _write(tmp_path / "auth_middleware.py", "# tier check\n" * 50)  # > 100 B
    _write(tmp_path / "tests" / "test_server.py", _good_server_py() + "\n" * 100)  # > 500 B
    _write(tmp_path / ".github" / "workflows" / "test.yml", _good_test_workflow())
    _write(tmp_path / ".github" / "workflows" / "ci.yml", _good_ci_workflow())
    _write(tmp_path / ".github" / "workflows" / "mcp-smithery-publish.yml", _good_publish_workflow())
    _write(tmp_path / "README.md", _good_readme())
    _write(tmp_path / "SECURITY.md", _good_security_md())
    return tmp_path


@pytest.fixture
def empty_repo(tmp_path: Path) -> Path:
    """An empty-shell repo that should score near 0."""
    return tmp_path


# --------------------------------------------------------------------- tests


def test_has_pyproject_toml_pass(good_repo: Path) -> None:
    c = check_has_pyproject_toml(good_repo)
    assert c.earned == 8 and c.points == 8


def test_has_pyproject_toml_fail(empty_repo: Path) -> None:
    c = check_has_pyproject_toml(empty_repo)
    assert c.earned == 0


def test_pyproject_uses_hatchling_pass(good_repo: Path) -> None:
    c = check_pyproject_uses_hatchling(good_repo)
    assert c.earned == 4


def test_pyproject_uses_hatchling_fail_wrong_backend(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", '[build-system]\nbuild-backend = "setuptools.build"\n')
    c = check_pyproject_uses_hatchling(tmp_path)
    assert c.earned == 0


def test_pyproject_only_includes_server_py_pass(good_repo: Path) -> None:
    c = check_pyproject_only_includes_server_py(good_repo)
    assert c.earned == 5


def test_pyproject_only_includes_server_py_bloated(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", textwrap.dedent("""\
        [build-system]
        build-backend = "hatchling.build"
        [project]
        name = "x"
        version = "0.1.0"
        [tool.hatch.build.targets.wheel]
        only-include = ["server.py", "data/", "src/", "tests/"]
        """))
    c = check_pyproject_only_includes_server_py(tmp_path)
    assert c.earned == 3  # gradated: server.py present, but > 2 files


def test_pyproject_declares_mcp_dep_pass(good_repo: Path) -> None:
    c = check_pyproject_declares_mcp_dep(good_repo)
    assert c.earned == 4


def test_pyproject_declares_mcp_dep_fail_old_version(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", textwrap.dedent("""\
        [build-system]
        build-backend = "hatchling.build"
        [project]
        name = "x"
        version = "0.1.0"
        dependencies = ["mcp==0.5.0"]
        """))
    c = check_pyproject_declares_mcp_dep(tmp_path)
    assert c.earned == 0


def test_pyproject_has_entry_point_pass(good_repo: Path) -> None:
    c = check_pyproject_has_entry_point(good_repo)
    assert c.earned == 2


def test_pyproject_has_entry_point_fail(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", textwrap.dedent("""\
        [build-system]
        build-backend = "hatchling.build"
        [project]
        name = "x"
        version = "0.1.0"
        """))
    c = check_pyproject_has_entry_point(tmp_path)
    assert c.earned == 0


def test_server_py_imports_clean_pass(good_repo: Path) -> None:
    c = check_server_py_imports_clean(good_repo)
    # Good server.py imports fine, so should pass.
    assert c.earned == 5


def test_server_py_imports_clean_fail_no_file(empty_repo: Path) -> None:
    c = check_server_py_imports_clean(empty_repo)
    assert c.earned == 0
    assert c.skipped is True


def test_server_declares_mcp_object_pass(good_repo: Path) -> None:
    c = check_server_declares_mcp_object(good_repo)
    assert c.earned == 4


def test_server_declares_mcp_object_fail(tmp_path: Path) -> None:
    _write(tmp_path / "server.py", "# no mcp object here\ndef foo():\n    pass\n")
    c = check_server_declares_mcp_object(tmp_path)
    assert c.earned == 0


def test_server_registers_at_least_one_tool_pass(good_repo: Path) -> None:
    c = check_server_registers_at_least_one_tool(good_repo)
    # 3 tools in good_server_py
    assert c.earned == 4


def test_server_registers_at_least_one_tool_warn(tmp_path: Path) -> None:
    src = textwrap.dedent('''\
        from mcp.server.fastmcp import FastMCP
        mcp = FastMCP("x")
        @mcp.tool()
        def only_one() -> str:
            """One tool."""
            return ""
        ''')
    _write(tmp_path / "server.py", src)
    c = check_server_registers_at_least_one_tool(tmp_path)
    assert c.earned == 2  # 1-2 tools = warn


def test_tool_names_unique_and_snake_case_pass(good_repo: Path) -> None:
    c = check_tool_names_unique_and_snake_case(good_repo)
    assert c.earned == 3


def test_tool_names_unique_and_snake_case_fail_dup(tmp_path: Path) -> None:
    src = textwrap.dedent('''\
        from mcp.server.fastmcp import FastMCP
        mcp = FastMCP("x")
        @mcp.tool(name="dup")
        def a() -> str:
            """a"""
            return ""
        @mcp.tool(name="dup")
        def b() -> str:
            """b"""
            return ""
        ''')
    _write(tmp_path / "server.py", src)
    c = check_tool_names_unique_and_snake_case(tmp_path)
    assert c.earned == 0


def test_all_tools_have_docstring_pass(good_repo: Path) -> None:
    c = check_all_tools_have_docstring(good_repo)
    assert c.earned == 3


def test_all_tools_have_docstring_fail(tmp_path: Path) -> None:
    src = (
        "from mcp.server.fastmcp import FastMCP\n"
        'mcp = FastMCP("x")\n'
        "@mcp.tool()\n"
        "def a() -> str:\n"
        '    return ""\n'
        "@mcp.tool()\n"
        "def b() -> str:\n"
        '    """docstring."""\n'
        '    return ""\n'
        "@mcp.tool()\n"
        "def c() -> str:\n"
        '    """docstring."""\n'
        '    return ""\n'
    )
    _write(tmp_path / "server.py", src)
    c = check_all_tools_have_docstring(tmp_path)
    assert c.earned == 1  # 2/3 docstringed (warn, not pass)


def test_has_auth_middleware_pass(good_repo: Path) -> None:
    c = check_has_auth_middleware(good_repo)
    assert c.earned == 3


def test_has_auth_middleware_fail(empty_repo: Path) -> None:
    c = check_has_auth_middleware(empty_repo)
    assert c.earned == 0


def test_has_real_test_file_pass(good_repo: Path) -> None:
    c = check_has_real_test_file(good_repo)
    assert c.earned == 3


def test_has_real_test_file_fail_stub(tmp_path: Path) -> None:
    """A test file that exists but is just a stub should not earn full points."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("# stub\n")
    c = check_has_real_test_file(tmp_path)
    assert c.earned == 0


def test_has_real_test_file_fail_no_tests(empty_repo: Path) -> None:
    c = check_has_real_test_file(empty_repo)
    assert c.earned == 0


def test_has_smithery_yaml_pass(good_repo: Path) -> None:
    c = check_has_smithery_yaml(good_repo)
    assert c.earned == 6


def test_smithery_yaml_is_declarative_pass(good_repo: Path) -> None:
    c = check_smithery_yaml_is_declarative(good_repo)
    assert c.earned == 3


def test_smithery_yaml_is_declarative_fail_runtime_block(tmp_path: Path) -> None:
    _write(tmp_path / "smithery.yaml", textwrap.dedent("""\
        name: x
        runtime: container
        startCommand:
          type: http
        """))
    c = check_smithery_yaml_is_declarative(tmp_path)
    assert c.earned == 0


def test_has_server_json_pass(good_repo: Path) -> None:
    c = check_has_server_json(good_repo)
    assert c.earned == 5


def test_has_server_json_fail_wrong_schema(tmp_path: Path) -> None:
    _write(tmp_path / "server.json", json.dumps({"name": "x", "version": "0.1.0"}))
    c = check_has_server_json(tmp_path)
    assert c.earned == 0


def test_has_well_known_server_card_pass(good_repo: Path) -> None:
    c = check_has_well_known_server_card(good_repo)
    assert c.earned == 4


def test_has_glama_json_pass(good_repo: Path) -> None:
    c = check_has_glama_json(good_repo)
    assert c.earned == 4


def test_has_glama_json_fail_wrong_maintainer(tmp_path: Path) -> None:
    _write(tmp_path / "glama.json", json.dumps({"maintainers": ["someone-else"]}))
    c = check_has_glama_json(tmp_path)
    assert c.earned == 0


def test_has_package_json_pass(good_repo: Path) -> None:
    c = check_has_package_json(good_repo)
    assert c.earned == 3


def test_has_package_json_warn_no_mcp_block(tmp_path: Path) -> None:
    _write(tmp_path / "package.json", json.dumps({"name": "x", "version": "0.1.0"}))
    c = check_has_package_json(tmp_path)
    assert c.earned == 1  # gradated: name present, but no mcp.entry


def test_has_dockerfile_glama_pass(good_repo: Path) -> None:
    c = check_has_dockerfile_glama(good_repo)
    assert c.earned == 4


def test_has_mcp_wrapper_pass(good_repo: Path) -> None:
    c = check_has_mcp_wrapper(good_repo)
    assert c.earned == 4


def test_has_mcp_wrapper_fail_no_health_route(tmp_path: Path) -> None:
    _write(tmp_path / "mcp-wrapper.py", textwrap.dedent('''\
        from server import mcp
        if __name__ == "__main__":
            mcp.run(transport="streamable-http")
        '''))
    c = check_has_mcp_wrapper(tmp_path)
    assert c.earned == 0


def test_has_test_workflow_pass(good_repo: Path) -> None:
    c = check_has_test_workflow(good_repo)
    assert c.earned == 3


def test_has_ci_workflow_pass(good_repo: Path) -> None:
    c = check_has_ci_workflow(good_repo)
    assert c.earned == 2


def test_has_smithery_publish_workflow_pass(good_repo: Path) -> None:
    c = check_has_smithery_publish_workflow(good_repo)
    assert c.earned == 2


def test_readme_has_install_features_license_pass(good_repo: Path) -> None:
    c = check_readme_has_install_features_license(good_repo)
    assert c.earned == 2


def test_readme_has_install_features_license_warn(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "## Install\n`pip install x`\n## Features\n- one\n")
    c = check_readme_has_install_features_license(tmp_path)
    assert c.earned == 1  # install + features, no license


def test_has_security_md_pass(good_repo: Path) -> None:
    c = check_has_security_md(good_repo)
    assert c.earned == 1


# ----------------------------------------------------------------- integration


def test_audit_gold_repo(good_repo: Path) -> None:
    """A repo that matches FLEET_BASE.md should score 100% in local mode."""
    sc = Audit().score(good_repo)
    assert sc.gate == GateVerdict.MERGE
    # Local-only run: 91 earned of 91 eligible (no wheel check, network probes SKIP).
    # The 7 SKIP-network points are not "lost" — they're just not in scope.
    assert sc.total_points == 91
    assert sc.eligible_points == 91  # 98 max - 7 network SKIPs
    assert sc.max_points == 98       # 100 - 2 wheel check (off by default)
    assert sc.score == 100           # 91/91 local-only passes 100%


def test_audit_empty_repo_blocks(empty_repo: Path) -> None:
    """Empty-shell repos should fail hard."""
    sc = Audit().score(empty_repo)
    assert sc.gate == GateVerdict.BLOCK
    assert sc.score < 5


def test_audit_with_wheel_check_sums_to_100(good_repo: Path) -> None:
    """With the wheel check enabled, eligible is 100 - 7 (3 network SKIPs) = 93."""
    sc = Audit(include_wheel_check=True).score(good_repo)
    assert sc.eligible_points == 93  # 100 - 7 (network probes always SKIP in local mode)
    assert sc.max_points == 100      # aspirational 100
    # Wheel check will pass since good_repo has a valid pyproject + server.py
    # (the build will succeed in the test env)
    assert sc.total_points >= 91
    assert sc.gate == GateVerdict.MERGE


def test_audit_category_minimums_satisfied(good_repo: Path) -> None:
    sc = Audit().score(good_repo)
    # All category minimums should be met for a gold-standard repo
    for cat, ok in sc.category_minimums_met.items():
        assert ok, f"category {cat} minimum not met: {sc.category_scores[cat]}/{sc.category_max[cat]}"


def test_audit_warnings_for_empty(empty_repo: Path) -> None:
    sc = Audit().score(empty_repo)
    # Should have at least 5 category-missed warnings + 1 total-missed warning
    assert len(sc.warnings) >= 5
    assert any("Total score" in w for w in sc.warnings)

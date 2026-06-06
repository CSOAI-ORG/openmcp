"""Shared pytest fixtures for the meok-cross-post test suite.

The `good_repo` and `empty_repo` fixtures are used by both test_audit.py
and test_render.py, so we extract them here (with their helper builders).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


# Per AGENTS.md hermeticity: never touch ~/.meok/. Run all tests under
# a temp HOME so any code path that reads keyring / home-dir config
# operates on a sandbox. Pytest fixture autouse=True applies this to
# every test in the directory tree.
@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Force every test to see a temporary HOME, never the real one."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / ".cache"))
    # Also unset anything that could be a sneaky hermeticity leak.
    monkeypatch.delenv("MEOK_ALLOW_NETWORK", raising=False)
    # Make sure no leftover dists from local builds pollute /tmp:
    os.makedirs(tmp_path, exist_ok=True)


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _good_pyproject() -> str:
    return (
        '[build-system]\n'
        'requires = ["hatchling"]\n'
        'build-backend = "hatchling.build"\n'
        '\n'
        '[project]\n'
        'name = "threat-intelligence"\n'
        'version = "0.1.0"\n'
        'dependencies = ["mcp>=1.0.0", "requests>=2.31"]\n'
        '\n'
        '[project.scripts]\n'
        'threat-intelligence = "server:main"\n'
        '\n'
        '[tool.hatch.build.targets.wheel]\n'
        'only-include = ["server.py"]\n'
    )


def _good_server_py() -> str:
    return (
        'from mcp.server.fastmcp import FastMCP\n'
        'mcp = FastMCP("threat-intelligence")\n'
        '\n'
        '@mcp.tool()\n'
        'async def cve_lookup(cve_id: str) -> str:\n'
        '    """Look up a CVE by id."""\n'
        '    return f"lookup {cve_id}"\n'
        '\n'
        '@mcp.tool()\n'
        'async def feed_update() -> str:\n'
        '    """Update the threat feed."""\n'
        '    return "ok"\n'
        '\n'
        '@mcp.tool()\n'
        'async def risk_score(target: str) -> str:\n'
        '    """Compute the risk score for a target."""\n'
        '    return "score"\n'
        '\n'
        'def main() -> None:\n'
        '    mcp.run()\n'
    )


def _good_smithery_yaml() -> str:
    return (
        'name: threat-intelligence\n'
        'description: CVE lookup\n'
        'version: 0.1.0\n'
        'tools:\n'
        '  - name: cve_lookup\n'
        '    description: Look up a CVE\n'
        '    parameters:\n'
        '      - name: cve_id\n'
        '        type: string\n'
        '        required: true\n'
        '  - name: feed_update\n'
        '    description: Update the threat feed\n'
        '  - name: risk_score\n'
        '    description: Compute a risk score\n'
    )


def _good_server_json() -> str:
    import json
    return json.dumps({
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        "name": "CSOAI-ORG/threat-intelligence-mcp",
        "version": "0.1.0",
        "description": "CVE lookup",
        "packages": [
            {"registryType": "pypi", "identifier": "threat-intelligence-mcp",
             "version": "0.1.0", "runtimeHint": "python",
             "transport": {"type": "stdio"}},
        ],
    })


def _good_server_card() -> str:
    import json
    return json.dumps({"name": "threat-intelligence-mcp", "description": "CVE lookup"})


def _good_glama_json() -> str:
    import json
    return json.dumps({
        "$schema": "https://glama.ai/mcp/schemas/server.json",
        "maintainers": ["CSOAI-ORG"],
    })


def _good_package_json() -> str:
    import json
    return json.dumps({
        "name": "@meok-ai-labs/threat-intelligence-mcp",
        "version": "0.1.0",
        "mcp": {"name": "threat-intelligence-mcp", "entry": "server:main"},
    })


def _good_dockerfile() -> str:
    return (
        'FROM python:3.11-slim\n'
        'WORKDIR /app\n'
        'COPY server.py /app/\n'
        'COPY mcp-wrapper.py /app/\n'
        'RUN pip install mcp>=1.0.0\n'
        'CMD ["python", "mcp-wrapper.py"]\n'
    )


def _good_wrapper() -> str:
    return (
        'from server import mcp\n'
        '\n'
        '@mcp.custom_route("/.well-known/mcp/server-card.json", methods=["GET"])\n'
        'async def card(_request):\n'
        '    return {}\n'
        '\n'
        '@mcp.tool()\n'
        'async def health() -> str:\n'
        '    """Return health."""\n'
        '    return "ok"\n'
        '\n'
        'if __name__ == "__main__":\n'
        '    mcp.settings.host = "0.0.0.0"\n'
        '    mcp.run(transport="streamable-http")\n'
    )


def _good_test_workflow() -> str:
    return (
        'name: Test\n'
        'on: [push]\n'
        'jobs:\n'
        '  test:\n'
        '    runs-on: ubuntu-latest\n'
        '    strategy:\n'
        '      matrix:\n'
        '        python-version: ["3.10", "3.11"]\n'
        '    steps:\n'
        '      - uses: actions/checkout@v4\n'
        '      - uses: actions/setup-python@v5\n'
        '        with: {python-version: ${{ matrix.python-version }}}\n'
        '      - run: pip install pytest mcp>=1.0.0\n'
        '      - run: pytest tests/\n'
    )


def _good_ci_workflow() -> str:
    return (
        'name: CI\n'
        'on: [push]\n'
        'jobs:\n'
        '  ruff:\n'
        '    runs-on: ubuntu-latest\n'
        '    steps:\n'
        '      - uses: actions/checkout@v4\n'
        '      - run: pip install ruff && ruff check .\n'
    )


def _good_publish_workflow() -> str:
    return (
        'name: Publish\n'
        'on:\n'
        '  release:\n'
        '    types: [published]\n'
        'jobs:\n'
        '  publish:\n'
        '    runs-on: ubuntu-latest\n'
        '    steps:\n'
        '      - uses: actions/checkout@v4\n'
        '      - run: npx @smithery/cli mcp publish\n'
    )


def _good_readme() -> str:
    return (
        '# threat-intelligence\n'
        '\n'
        '## Install\n'
        'pip install threat-intelligence-mcp\n'
        '\n'
        '## Features\n'
        '- CVE lookup\n'
        '- Feed update\n'
        '\n'
        '## License\n'
        'Apache-2.0\n'
    )


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
    _write(tmp_path / "auth_middleware.py", "# tier check\n" * 50)
    _write(tmp_path / "tests" / "test_server.py", _good_server_py() + "\n" * 100)
    _write(tmp_path / ".github" / "workflows" / "test.yml", _good_test_workflow())
    _write(tmp_path / ".github" / "workflows" / "ci.yml", _good_ci_workflow())
    _write(tmp_path / ".github" / "workflows" / "mcp-smithery-publish.yml", _good_publish_workflow())
    _write(tmp_path / "README.md", _good_readme())
    _write(tmp_path / "SECURITY.md", _good_security_md())
    return tmp_path


@pytest.fixture
def empty_repo(tmp_path: Path) -> Path:
    """An empty-shell repo that should score near 0."""
    _write(tmp_path / ".gitignore", "node_modules/\n__pycache__/\n")
    _write(tmp_path / "LICENSE", "Apache-2.0\n" * 200)
    _write(tmp_path / "package.json", '{"name": "x", "version": "0.0.0"}')
    _write(tmp_path / "README.md", "# placeholder\n")
    return tmp_path

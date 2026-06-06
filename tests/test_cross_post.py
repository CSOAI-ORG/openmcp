"""Tests for the cross_post orchestrator + the 3 directory clients.

Uses unittest.mock.patch on the requests module (the clients use
`requests.put` / `requests.post` / `requests.get`). Per AGENTS.md
hermeticity: no real network.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError

from meok_cross_post import cross_post, mcp_registry, smithery


# ----------------------------------------------------------------- preflight


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _good_metadata(tmp_path: Path) -> Path:
    _write(tmp_path / "smithery.yaml", textwrap.dedent("""\
        name: threat-intelligence
        description: CVE lookup
        version: 0.1.0
        tools:
          - name: cve_lookup
            description: Look up a CVE
            parameters:
              - name: cve_id
                type: string
                required: true
        """))
    _write(tmp_path / "server.json", json.dumps({
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        "name": "CSOAI-ORG/threat-intelligence-mcp",
        "version": "0.1.0",
        "description": "CVE lookup",
        "packages": [
            {"registryType": "pypi", "identifier": "threat-intelligence-mcp",
             "version": "0.1.0", "runtimeHint": "python",
             "transport": {"type": "stdio"}},
        ],
    }))
    _write(tmp_path / ".well-known" / "mcp" / "server-card.json", json.dumps({
        "name": "threat-intelligence-mcp", "description": "CVE lookup",
    }))
    _write(tmp_path / "glama.json", json.dumps({"maintainers": ["CSOAI-ORG"]}))
    _write(tmp_path / "package.json", json.dumps({
        "name": "@meok-ai-labs/threat-intelligence-mcp",
        "version": "0.1.0",
        "mcp": {"name": "threat-intelligence-mcp", "entry": "server:main"},
    }))
    return tmp_path


def test_preflight_passes_on_consistent_metadata(tmp_path: Path) -> None:
    repo = _good_metadata(tmp_path)
    ok, errors, md = cross_post.preflight(repo)
    assert ok is True
    assert errors == []
    assert "smithery.yaml" in md
    assert "server.json" in md


def test_preflight_fails_on_name_mismatch(tmp_path: Path) -> None:
    repo = _good_metadata(tmp_path)
    # Corrupt server.json's package identifier
    p = repo / "server.json"
    j = json.loads(p.read_text())
    j["packages"][0]["identifier"] = "wrong-name"
    p.write_text(json.dumps(j))
    ok, errors, _ = cross_post.preflight(repo)
    assert ok is False
    assert any("name mismatch" in e for e in errors)


def test_preflight_fails_on_missing_tools(tmp_path: Path) -> None:
    repo = _good_metadata(tmp_path)
    _write(repo / "smithery.yaml", "name: x\ndescription: y\nversion: 0.1.0\n")
    ok, errors, _ = cross_post.preflight(repo)
    assert ok is False
    assert any("no `tools:`" in e for e in errors)


# -------------------------------------------------------------- smithery.py


def test_smithery_publish_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SMITHERY_API_KEY", raising=False)
    result = smithery.publish("nicholastempleman", "test", "Test", "Desc")
    assert result["ok"] is False
    assert "SMITHERY_API_KEY" in result["message"]


def test_smithery_publish_201_created(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMITHERY_API_KEY", "fake-key")
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    with patch("meok_cross_post.smithery.requests.put", return_value=mock_resp) as mp:
        result = smithery.publish("nicholastempleman", "test", "Test", "Desc")
        assert mp.called
    assert result["ok"] is True
    assert result["status_code"] == 201


def test_smithery_publish_200_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMITHERY_API_KEY", "fake-key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("meok_cross_post.smithery.requests.put", return_value=mock_resp):
        result = smithery.publish("nicholastempleman", "test", "Test", "Desc")
    assert result["ok"] is True
    assert result["status_code"] == 200
    assert "idempotent" in result["message"]


def test_smithery_publish_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMITHERY_API_KEY", "bad-key")
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "unauthorized"
    with patch("meok_cross_post.smithery.requests.put", return_value=mock_resp):
        result = smithery.publish("nicholastempleman", "test", "Test", "Desc")
    assert result["ok"] is False
    assert result["status_code"] == 401
    assert "auth failed" in result["message"]


def test_smithery_publish_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMITHERY_API_KEY", "fake-key")
    with patch("meok_cross_post.smithery.requests.put",
               side_effect=RequestsConnectionError("nope")):
        result = smithery.publish("nicholastempleman", "test", "Test", "Desc")
    assert result["ok"] is False
    assert "connection error" in result["message"]


# -------------------------------------------------------------- mcp_registry


def test_mcp_registry_publish_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with patch("keyring.get_password", return_value=None):
        result = mcp_registry.publish({"name": "io.github.x/y", "version": "0.1.0"})
    assert result["ok"] is False
    assert "GITHUB_TOKEN" in result["message"] or "keyring" in result["message"]


def test_mcp_registry_publish_409_is_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Registry returns 409 on repeat (name, version). We treat as success."""
    monkeypatch.setenv("GITHUB_TOKEN", "fake-pat")

    jwt_resp = MagicMock()
    jwt_resp.status_code = 200
    jwt_resp.json.return_value = {"jwt": "fake-jwt"}

    pub_resp = MagicMock()
    pub_resp.status_code = 409
    pub_resp.text = "already exists"

    with patch("meok_cross_post.mcp_registry.requests.post",
               side_effect=[jwt_resp, pub_resp]) as mp:
        result = mcp_registry.publish({"name": "io.github.x/y", "version": "0.1.0"})
        assert mp.call_count == 2
    assert result["ok"] is True
    assert result["status_code"] == 409
    assert "idempotent" in result["message"]


def test_mcp_registry_publish_201_created(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "fake-pat")

    jwt_resp = MagicMock()
    jwt_resp.status_code = 200
    jwt_resp.json.return_value = {"jwt": "fake-jwt"}

    pub_resp = MagicMock()
    pub_resp.status_code = 201
    pub_resp.json.return_value = {"id": "abc123"}
    pub_resp.text = "ok"

    with patch("meok_cross_post.mcp_registry.requests.post",
               side_effect=[jwt_resp, pub_resp]):
        result = mcp_registry.publish({"name": "io.github.x/y", "version": "0.1.0"})
    assert result["ok"] is True
    assert result["status_code"] == 201
    assert "created" in result["message"]


def test_mcp_registry_jwt_exchange_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "bad-pat")

    jwt_resp = MagicMock()
    jwt_resp.status_code = 401
    jwt_resp.text = "bad token"

    with patch("meok_cross_post.mcp_registry.requests.post", return_value=jwt_resp):
        result = mcp_registry.publish({"name": "io.github.x/y", "version": "0.1.0"})
    assert result["ok"] is False
    assert result["status_code"] == 401
    assert "JWT exchange" in result["message"]


# -------------------------------------------------------------- docker template


def test_docker_template_written(tmp_path: Path) -> None:
    repo = _good_metadata(tmp_path)
    ok, _, md = cross_post.preflight(repo)
    assert ok
    template = cross_post.write_docker_template(repo, md)
    assert template.is_file()
    assert template.name.endswith("-docker-catalog.yaml")
    assert "docker-catalog.yaml" in template.name
    text = template.read_text()
    # The repo's package name is the smithery.yaml name; for tmp_path
    # pytest dirs that's the test name (e.g. test_docker_template_written0).
    # The template should mention that name.
    assert "title:" in text
    assert "ghcr.io/csoai-org/" in text
    assert "cve_lookup" in text


# -------------------------------------------------------------- end-to-end


def test_cross_post_run_no_auth_envs(tmp_path: Path) -> None:
    """When no env vars are set, both directories skip with hints — exit 0."""
    import os as _os
    repo = _good_metadata(tmp_path)
    saved = {}
    for k in ("SMITHERY_API_KEY", "GITHUB_TOKEN", "GH_TOKEN", "MEOK_ALLOW_NETWORK"):
        if k in _os.environ:
            saved[k] = _os.environ.pop(k)
    try:
        with patch("keyring.get_password", return_value=None):
            result = cross_post.run(repo)
    finally:
        _os.environ.update(saved)
    assert result.preflight_ok is True
    assert len(result.directories) == 2
    # Both should be marked "not ok" with a clear env-var hint
    smithery_result = next(d for d in result.directories if d.directory == "smithery")
    assert smithery_result.ok is False
    assert "SMITHERY_API_KEY" in smithery_result.message
    registry_result = next(d for d in result.directories if d.directory == "mcp_registry")
    assert registry_result.ok is False
    # Manual checklist should still be populated
    assert "Docker MCP Catalog" in result.manual_checklist
    assert "Glama" in result.manual_checklist


def test_cross_post_run_preflight_fails(tmp_path: Path) -> None:
    """Inconsistent metadata should refuse to publish, even with all env vars set."""
    repo = tmp_path  # empty
    result = cross_post.run(repo)
    assert result.preflight_ok is False
    assert len(result.preflight_errors) > 0
    assert result.directories == []

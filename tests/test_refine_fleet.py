"""Tests for the parallel cross-post fan-out, `refine`, and `fleet`.

Hermetic — no real network. The directory publish() clients are mocked
(or simply hit their no-env-var skip path). The `good_repo`/`empty_repo`
fixtures come from conftest.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from meok_cross_post import cross_post, fleet, scaffold
from meok_cross_post.cli import main
from meok_cross_post.refine import gap_report
from meok_cross_post.schema import DirectoryResult


# ===================================================================
# FEATURE 1 — parallel fan-out in cross_post.run()
# ===================================================================


def test_run_returns_all_directory_results(tmp_path: Path) -> None:
    """Parallel run still returns both directory results, in fixed order."""
    from tests.test_cross_post import _good_metadata
    repo = _good_metadata(tmp_path)

    def fake_smithery(repo, md):
        return DirectoryResult(directory="smithery", ok=True, status_code=201, message="published")

    def fake_registry(repo, md):
        return DirectoryResult(directory="mcp_registry", ok=True, status_code=201, message="created")

    with patch.object(cross_post, "_push_smithery", side_effect=fake_smithery), \
         patch.object(cross_post, "_push_mcp_registry", side_effect=fake_registry):
        result = cross_post.run(repo)

    assert result.preflight_ok is True
    labels = [d.directory for d in result.directories]
    assert labels == ["smithery", "mcp_registry"]
    assert all(d.ok for d in result.directories)


def test_run_one_directory_failure_does_not_kill_others(tmp_path: Path) -> None:
    """A raised exception in one directory is captured; the other still runs."""
    from tests.test_cross_post import _good_metadata
    repo = _good_metadata(tmp_path)

    def boom(repo, md):
        raise RuntimeError("smithery API exploded")

    def ok_registry(repo, md):
        return DirectoryResult(directory="mcp_registry", ok=True, status_code=201, message="created")

    with patch.object(cross_post, "_push_smithery", side_effect=boom), \
         patch.object(cross_post, "_push_mcp_registry", side_effect=ok_registry):
        result = cross_post.run(repo)

    assert result.preflight_ok is True
    sm = next(d for d in result.directories if d.directory == "smithery")
    reg = next(d for d in result.directories if d.directory == "mcp_registry")
    assert sm.ok is False
    assert "error" in sm.message and "exploded" in sm.message
    # The other directory must have completed normally.
    assert reg.ok is True
    assert reg.status_code == 201


# ===================================================================
# FEATURE 2 — `refine`
# ===================================================================


def test_refine_passing_repo_reports_ready(good_repo: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["refine", str(good_repo), "--no-post"])
    assert result.exit_code == 0, result.output
    assert "READY" in result.output
    assert "MERGE" in result.output


def test_refine_no_post_never_calls_publish(good_repo: Path) -> None:
    runner = CliRunner()
    with patch("meok_cross_post.smithery.publish") as sm_pub, \
         patch("meok_cross_post.mcp_registry.publish") as reg_pub:
        result = runner.invoke(main, ["refine", str(good_repo), "--no-post"])
    assert result.exit_code == 0, result.output
    assert not sm_pub.called
    assert not reg_pub.called


def test_refine_below_gate_prints_gap_report(empty_repo: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["refine", str(empty_repo)])
    assert result.exit_code == 1
    assert "GAP REPORT" in result.output
    assert "FIX:" in result.output
    # Grouped by category — at least one category header should appear.
    assert "C_discovery" in result.output


def test_refine_scaffold_creates_safe_files_and_raises_score(tmp_path: Path) -> None:
    """A bare-but-buildable repo: scaffold the discovery files, score goes up."""
    # Minimal repo with a real server.py + pyproject so the non-discovery
    # checks already pass; only the static discovery files are missing.
    from tests.conftest import (
        _good_pyproject, _good_server_py, _good_dockerfile, _good_wrapper,
        _good_test_workflow, _good_ci_workflow, _good_publish_workflow,
        _good_readme, _write,
    )
    _write(tmp_path / "pyproject.toml", _good_pyproject())
    _write(tmp_path / "server.py", _good_server_py())
    _write(tmp_path / "Dockerfile.glama", _good_dockerfile())
    _write(tmp_path / "mcp-wrapper.py", _good_wrapper())
    _write(tmp_path / "auth_middleware.py", "# tier check\n" * 50)
    _write(tmp_path / "tests" / "test_server.py", _good_server_py() + "\n" * 100)
    _write(tmp_path / ".github" / "workflows" / "test.yml", _good_test_workflow())
    _write(tmp_path / ".github" / "workflows" / "ci.yml", _good_ci_workflow())
    _write(tmp_path / ".github" / "workflows" / "mcp-smithery-publish.yml",
           _good_publish_workflow())
    _write(tmp_path / "README.md", _good_readme())

    from meok_cross_post.audit import score as audit_score
    before = audit_score(tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["refine", str(tmp_path), "--scaffold", "--no-post"])
    assert result.exit_code == 0, result.output
    assert "Scaffolded safe discovery files" in result.output

    after = audit_score(tmp_path)
    assert after.score > before.score
    assert after.gate.value == "merge"
    # The safe files were actually written.
    for rel in ("smithery.yaml", "server.json", "glama.json", "package.json",
                "SECURITY.md", ".well-known/mcp/server-card.json"):
        assert (tmp_path / rel).is_file()
    # server.py was NOT overwritten.
    assert (tmp_path / "server.py").read_text() == _good_server_py()


def test_scaffold_does_not_overwrite_existing(tmp_path: Path) -> None:
    from tests.conftest import _good_pyproject, _write
    _write(tmp_path / "pyproject.toml", _good_pyproject())
    _write(tmp_path / "SECURITY.md", "ORIGINAL security@x.com\n")
    written = scaffold.scaffold(tmp_path)
    assert "SECURITY.md" not in written
    assert (tmp_path / "SECURITY.md").read_text() == "ORIGINAL security@x.com\n"
    # but smithery.yaml etc. were created
    assert "smithery.yaml" in written
    assert (tmp_path / "smithery.yaml").is_file()


def test_scaffold_never_touches_server_py(tmp_path: Path) -> None:
    from tests.conftest import _good_pyproject, _write
    _write(tmp_path / "pyproject.toml", _good_pyproject())
    scaffold.scaffold(tmp_path)
    assert not (tmp_path / "server.py").exists()


# ===================================================================
# FEATURE 3 — `fleet`
# ===================================================================


def _bare_repo(path: Path) -> Path:
    from tests.conftest import _write
    _write(path / "pyproject.toml", "[project]\nname = \"x\"\nversion = \"0.0.0\"\n")
    _write(path / "README.md", "# placeholder\n")
    return path


def test_fleet_aggregates_sorted_with_pass_count(tmp_path: Path) -> None:
    from tests.conftest import (
        _good_pyproject, _good_server_py, _good_smithery_yaml, _good_server_json,
        _good_server_card, _good_glama_json, _good_package_json, _good_dockerfile,
        _good_wrapper, _good_test_workflow, _good_ci_workflow, _good_publish_workflow,
        _good_readme, _good_security_md, _write,
    )
    # repo A — full (should be MERGE)
    a = tmp_path / "alpha"
    _write(a / "pyproject.toml", _good_pyproject())
    _write(a / "server.py", _good_server_py())
    _write(a / "smithery.yaml", _good_smithery_yaml())
    _write(a / "server.json", _good_server_json())
    _write(a / ".well-known" / "mcp" / "server-card.json", _good_server_card())
    _write(a / "glama.json", _good_glama_json())
    _write(a / "package.json", _good_package_json())
    _write(a / "Dockerfile.glama", _good_dockerfile())
    _write(a / "mcp-wrapper.py", _good_wrapper())
    _write(a / "auth_middleware.py", "# tier check\n" * 50)
    _write(a / "tests" / "test_server.py", _good_server_py() + "\n" * 100)
    _write(a / ".github" / "workflows" / "test.yml", _good_test_workflow())
    _write(a / ".github" / "workflows" / "ci.yml", _good_ci_workflow())
    _write(a / ".github" / "workflows" / "mcp-smithery-publish.yml", _good_publish_workflow())
    _write(a / "README.md", _good_readme())
    _write(a / "SECURITY.md", _good_security_md())
    # repo B — bare (BLOCK)
    b = _bare_repo(tmp_path / "bravo")

    cards = fleet.audit_many([b, a])  # pass unsorted
    # sorted by score desc — alpha first
    assert [c.repo_name for c in cards] == ["alpha", "bravo"]
    assert cards[0].score > cards[1].score

    md = fleet.scoreboard_markdown(cards)
    assert "| Repo | Score | Gate | Top failing category |" in md
    assert "1 passing" in md  # only alpha passes
    assert "2 repos" in md

    js = fleet.scoreboard_json(cards)
    assert js["count"] == 2
    assert js["passing"] == 1
    assert js["repos"][0]["repo"] == "alpha"
    assert js["repos"][0]["gate"] == "merge"


def test_fleet_discover_repos_globs_pyproject_subdirs(tmp_path: Path) -> None:
    _bare_repo(tmp_path / "one")
    _bare_repo(tmp_path / "two")
    (tmp_path / "nope").mkdir()  # no pyproject — excluded
    repos = fleet.discover_repos(tmp_path)
    names = sorted(r.name for r in repos)
    assert names == ["one", "two"]


def test_fleet_cli_json_and_threshold(tmp_path: Path) -> None:
    a = _bare_repo(tmp_path / "alpha")
    b = _bare_repo(tmp_path / "bravo")
    runner = CliRunner()
    result = runner.invoke(main, ["fleet", str(a), str(b), "--json", "--threshold", "0"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["count"] == 2
    assert data["threshold"] == 0
    # threshold 0 — anything with gate MERGE passes; bare repos are BLOCK so 0
    assert data["passing"] == 0


def test_fleet_cli_no_repos_errors(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(main, ["fleet"])
    assert result.exit_code == 1
    assert "No repos found" in result.output


# ===================================================================
# gap_report unit
# ===================================================================


def test_gap_report_lists_fixes_grouped_by_category(empty_repo: Path) -> None:
    from meok_cross_post.audit import score as audit_score
    sc = audit_score(empty_repo)
    report = gap_report(sc)
    assert "GAP REPORT" in report
    assert "FIX:" in report
    assert "smithery.yaml" in report  # remediation text for has_smithery_yaml

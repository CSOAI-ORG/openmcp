"""Snapshot tests for the scorecard markdown renderer."""

from __future__ import annotations

from meok_cross_post.audit import score as audit_score
from meok_cross_post.render import scorecard_markdown
from meok_cross_post.schema import GateVerdict


def test_scorecard_markdown_gold(good_repo) -> None:
    sc = audit_score(good_repo)
    md = scorecard_markdown(sc)
    # Spot-check the rendered markdown
    assert f"### {sc.repo_name}:" in md
    assert "MERGE" in md
    assert "| Category | Score | Min | Status |" in md
    assert "has_pyproject_toml" in md
    # Every check should appear as a row
    for c in sc.checks:
        assert f"`{c.id}`" in md


def test_scorecard_markdown_empty(empty_repo) -> None:
    sc = audit_score(empty_repo)
    md = scorecard_markdown(sc)
    assert "BLOCK" in md
    assert "**Warnings:**" in md
    assert "Category minimum missed" in md

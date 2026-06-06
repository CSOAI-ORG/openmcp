"""Scorecard → markdown table for PR comments and Slack.

Used by:
  - `meok-cross-post audit --format markdown` (CLI)
  - PR-comment bot (separate workflow, not in this repo)
  - Monthly cron (CSV-ish summary)
"""

from __future__ import annotations

from typing import Dict, List

from meok_cross_post.schema import CheckResult, CheckStatus, GateVerdict, ScoreCard


_GATE_BADGE: Dict[GateVerdict, str] = {
    GateVerdict.MERGE: "🟢 MERGE",
    GateVerdict.REVIEW: "🟡 REVIEW",
    GateVerdict.BLOCK: "🔴 BLOCK",
}


_STATUS_BADGE: Dict[CheckStatus, str] = {
    CheckStatus.PASS: "✅",
    CheckStatus.WARN: "⚠️ ",
    CheckStatus.FAIL: "❌",
    CheckStatus.SKIP: "⏭️ ",
}


def scorecard_markdown(sc: ScoreCard) -> str:
    """Render a ScoreCard as a GitHub-flavored markdown report.

    Example output:

        ### threat-intelligence: 🟢 MERGE (91/91, 100%)

        | Category | Score | Min | Status |
        |---|---|---|---|
        | A_installability | 23/23 | 18 | ✅ |
        | B_server | 25/25 | 12 | ✅ |
        | C_discovery | 25/25 | 14 | ✅ |
        | D_distribution | 8/15 | 6 | ✅ |
        | E_cicd | 10/10 | 5 | ✅ |

        | Check | Cat | Earned | Status | Evidence |
        |---|---|---|---|---|
        | has_pyproject_toml | A | 8/8 | ✅ | pyproject.toml present at ... |
        ...
    """
    lines: List[str] = []

    # Header
    badge = _GATE_BADGE.get(sc.gate, str(sc.gate))
    pct = round((sc.total_points / sc.eligible_points) * 100) if sc.eligible_points else 0
    lines.append(f"### {sc.repo_name}: {badge} ({sc.total_points}/{sc.eligible_points}, {pct}%)")
    lines.append("")

    # Category summary
    lines.append("| Category | Score | Min | Status |")
    lines.append("|---|---|---|---|")
    mins = sc.category_minimums_met
    for cat, max_pts in sc.category_max.items():
        got = sc.category_scores.get(cat, 0)
        ok = mins.get(cat, False)
        badge = "✅" if ok else "❌"
        lines.append(f"| {cat} | {got}/{max_pts} | (see min) | {badge} |")
    lines.append("")

    # Per-check details (grouped by category)
    lines.append("| Check | Cat | Earned | Status | Evidence |")
    lines.append("|---|---|---|---|---|")
    for c in sc.checks:
        badge = _STATUS_BADGE.get(c.status, "?")
        ev = (c.evidence or "").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| `{c.id}` | {c.category[0]} | {c.earned}/{c.points} | {badge} | {ev} |")
    lines.append("")

    # Warnings
    if sc.warnings:
        lines.append("**Warnings:**")
        for w in sc.warnings:
            lines.append(f"- {w}")
        lines.append("")

    return "\n".join(lines)


def scorecard_summary_csv_line(sc: ScoreCard) -> str:
    """One CSV line for the monthly cron output. Header is the caller's problem."""
    return (
        f"{sc.repo_name},{sc.total_points},{sc.eligible_points},"
        f"{sc.score},{sc.gate.value},"
        f"{sc.category_scores.get('A_installability', 0)}/{sc.category_max.get('A_installability', 0)},"
        f"{sc.category_scores.get('B_server', 0)}/{sc.category_max.get('B_server', 0)},"
        f"{sc.category_scores.get('C_discovery', 0)}/{sc.category_max.get('C_discovery', 0)},"
        f"{sc.category_scores.get('D_distribution', 0)}/{sc.category_max.get('D_distribution', 0)},"
        f"{sc.category_scores.get('E_cicd', 0)}/{sc.category_max.get('E_cicd', 0)}"
    )

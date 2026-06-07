"""Fleet scoreboard: audit many repos in parallel into one ranked view.

Audits are independent, so they fan out via a ThreadPoolExecutor. Workers
are kept modest (default 4) because the audit's
`check_server_py_imports_clean` spawns a subprocess per repo.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from meok_cross_post.audit import score as audit_score
from meok_cross_post.schema import GateVerdict, ScoreCard

_GATE_EMOJI: Dict[GateVerdict, str] = {
    GateVerdict.MERGE: "🟢",
    GateVerdict.REVIEW: "🟡",
    GateVerdict.BLOCK: "🔴",
}


def discover_repos(cwd: Path) -> List[Path]:
    """Immediate subdirectories of cwd that contain a pyproject.toml, sorted."""
    cwd = Path(cwd).resolve()
    out = [
        child for child in sorted(cwd.iterdir())
        if child.is_dir() and (child / "pyproject.toml").is_file()
    ]
    return out


def audit_many(
    repos: List[Path],
    allow_network: bool = False,
    max_workers: int = 4,
    score_fn: Optional[Callable[..., ScoreCard]] = None,
) -> List[ScoreCard]:
    """Audit each repo (in parallel) and return ScoreCards sorted by score desc."""
    fn = score_fn or audit_score
    if not repos:
        return []

    def _one(repo: Path) -> ScoreCard:
        return fn(repo, allow_network=allow_network)

    with ThreadPoolExecutor(max_workers=min(max_workers, len(repos))) as pool:
        cards = list(pool.map(_one, repos))

    cards.sort(key=lambda c: (-c.score, c.repo_name))
    return cards


def _top_failing_category(sc: ScoreCard) -> str:
    """The category furthest below its max (the biggest point gap)."""
    worst = ""
    worst_gap = -1
    for cat, max_pts in sc.category_max.items():
        gap = max_pts - sc.category_scores.get(cat, 0)
        if gap > worst_gap:
            worst_gap = gap
            worst = cat
    return worst if worst_gap > 0 else "—"


def scoreboard_markdown(cards: List[ScoreCard], threshold: int = 80) -> str:
    """Render a ranked markdown scoreboard + a summary line."""
    lines: List[str] = [
        "| Repo | Score | Gate | Top failing category |",
        "|---|---|---|---|",
    ]
    passing = 0
    for sc in cards:
        emoji = _GATE_EMOJI.get(sc.gate, "?")
        if sc.gate == GateVerdict.MERGE and sc.score >= threshold:
            passing += 1
        lines.append(
            f"| {sc.repo_name} | {sc.score} | {emoji} | {_top_failing_category(sc)} |"
        )
    n = len(cards)
    mean = round(sum(c.score for c in cards) / n, 1) if n else 0.0
    lines.append("")
    lines.append(
        f"**{n} repos, {passing} passing (MERGE, score ≥ {threshold}), mean score {mean}.**"
    )
    return "\n".join(lines)


def scoreboard_json(cards: List[ScoreCard], threshold: int = 80) -> Dict[str, Any]:
    """Machine-readable scoreboard."""
    n = len(cards)
    passing = sum(
        1 for c in cards if c.gate == GateVerdict.MERGE and c.score >= threshold
    )
    mean = round(sum(c.score for c in cards) / n, 1) if n else 0.0
    return {
        "threshold": threshold,
        "count": n,
        "passing": passing,
        "mean_score": mean,
        "repos": [
            {
                "repo": sc.repo_name,
                "path": sc.repo,
                "score": sc.score,
                "gate": sc.gate.value,
                "top_failing_category": _top_failing_category(sc),
            }
            for sc in cards
        ],
    }

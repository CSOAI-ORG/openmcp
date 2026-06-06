"""Pydantic models for meok-cross-post.

These are the public data shapes used by `audit.py`, `cross_post.py`,
`render.py`, and `mcp_server.py`. They serialize cleanly to JSON for the
PR-comment bot and the monthly-cron CSV.
"""

from __future__ import annotations

import enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------- enums


class CheckStatus(str, enum.Enum):
    """A check can be PASS (full points), WARN (partial), or FAIL (zero)."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"    # not run (e.g. network probe with allow_network=False)


class GateVerdict(str, enum.Enum):
    """Aggregate gate decision."""

    MERGE = "merge"          # score >= 80 AND every category minimum met
    REVIEW = "review"        # 60 <= score < 80 OR a category minimum missed
    BLOCK = "block"          # score < 60


# ------------------------------------------------------------------ check row


class CheckResult(BaseModel):
    """One rubric check's result."""

    id: str                                              # "has_pyproject_toml"
    category: str                                         # "A_installability"
    points: int                                           # max possible
    earned: int                                           # 0..points
    status: CheckStatus
    evidence: str = ""                                    # one-line human-readable reason
    gradated: bool = False                                # true if earned < points for any reason
    cost: str = ""                                        # "1 fs read", "~150ms network", etc.


# ----------------------------------------------------------------- scorecard


class ScoreCard(BaseModel):
    """Full scorecard for one repo, returned by Audit.score()."""

    repo: str                                            # absolute path
    repo_name: str                                       # basename (e.g. "threat-intelligence")
    total_points: int = 0
    max_points: int = 100                                # aspirational full-rubric max
    eligible_points: int = 0                             # actual max for THIS run (100 - skipped check points)
    score: int = 0                                       # total / eligible * 100, rounded
    gate_threshold: int = 80
    warn_threshold: int = 60
    gate: GateVerdict = GateVerdict.BLOCK
    category_scores: Dict[str, int] = Field(default_factory=dict)
    category_max: Dict[str, int] = Field(default_factory=dict)
    category_minimums_met: Dict[str, bool] = Field(default_factory=dict)
    checks: List[CheckResult] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)    # human-readable warnings
    generated_at: str = ""                               # ISO 8601

    def to_markdown(self) -> str:
        """Render as a GitHub-flavored markdown table. Implemented in render.py."""
        from meok_cross_post.render import scorecard_markdown
        return scorecard_markdown(self)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


# ------------------------------------------------------------ cross-post result


class DirectoryResult(BaseModel):
    """Result of one cross-post call (one directory)."""

    directory: str                                       # "smithery" | "mcp_registry"
    ok: bool                                             # True on 2xx or 409-conflict-as-success
    status_code: Optional[int] = None
    message: str = ""
    skipped_reason: str = ""                             # e.g. "SMITHERY_API_KEY env var not set"


class CrossPostResult(BaseModel):
    """Result of cross_post.run() for one repo."""

    repo: str
    repo_name: str
    preflight_ok: bool                                   # False if metadata files disagree
    preflight_errors: List[str] = Field(default_factory=list)
    directories: List[DirectoryResult] = Field(default_factory=list)
    manual_checklist: str = ""                           # markdown, ready to print
    generated_at: str = ""


# ----------------------------------------------------- manual checklist entry


class ManualChecklistItem(BaseModel):
    """One line in the manual checklist."""

    directory: str
    url: str                                             # exact URL the user must visit
    action: str                                          # one-line action ("open PR", "click Add Server")
    template_path: str = ""                              # local file the user should `cp` into the PR
    notes: str = ""

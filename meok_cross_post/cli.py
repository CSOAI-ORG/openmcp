"""CLI entry point for meok-cross-post.

Subcommands:
  audit        Score a flagship repo 0-100 against FLEET_BASE.md
  cross-post   Push metadata to Smithery + MCP Registry
  checklist    Print the manual directory submission checklist
  all          audit + cross-post + checklist, in that order
  refine       audit → gap-report (→ scaffold) → re-audit → gate → cross-post
  fleet        Audit many repos into one scoreboard
  auth         One-time auth bootstrap (GitHub PAT → keyring)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from meok_cross_post import __version__
from meok_cross_post import fleet as fleet_mod
from meok_cross_post import scaffold as scaffold_mod
from meok_cross_post.audit import Audit, score as audit_score
from meok_cross_post.cross_post import run as cross_post_run
from meok_cross_post.manual_checklist import render_checklist
from meok_cross_post.refine import gap_report
from meok_cross_post.render import scorecard_markdown


@click.group()
@click.version_option(version=__version__, prog_name="meok-cross-post")
def main() -> None:
    """Audit + cross-post flagship MCP servers to all top directories."""


@main.command()
@click.argument("repo", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--network", is_flag=True, default=False,
              help="Enable 3 network probes (GHCR, Smithery, MCP Registry).")
@click.option("--include-wheel-check", is_flag=True, default=False,
              help="Run `python -m build` to verify the wheel ships clean. Adds ~3s.")
@click.option("--format", "fmt", type=click.Choice(["markdown", "json"]), default="markdown",
              help="Output format. Default: markdown.")
def audit(repo: Path, network: bool, include_wheel_check: bool, fmt: str) -> None:
    """Score REPO 0-100 against FLEET_BASE.md."""
    if network:
        os.environ["MEOK_ALLOW_NETWORK"] = "1"

    sc = audit_score(repo, allow_network=network, include_wheel_check=include_wheel_check)

    if fmt == "json":
        click.echo(json.dumps(sc.to_dict(), indent=2))
    else:
        click.echo(sc.to_markdown())

    # Exit code reflects the gate verdict — useful in CI.
    if sc.gate.value == "block":
        sys.exit(1)
    elif sc.gate.value == "review":
        sys.exit(2)
    sys.exit(0)


@main.command("cross-post")
@click.argument("repo", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text")
def cross_post(repo: Path, fmt: str) -> None:
    """Push REPO's metadata to Smithery + MCP Registry.

    Prints the result for each directory (or skips with a hint if the
    required env var is missing). Always prints the manual checklist at
    the end for the 4 directories without public APIs.
    """
    result = cross_post_run(repo)
    if not result.preflight_ok:
        click.echo("Pre-flight FAILED — refusing to publish inconsistent metadata:", err=True)
        for e in result.preflight_errors:
            click.echo(f"  - {e}", err=True)
        sys.exit(1)

    if fmt == "json":
        click.echo(json.dumps(result.model_dump(mode="json"), indent=2))
    else:
        click.echo(f"=== Cross-post results for {result.repo_name} ===")
        for d in result.directories:
            status = "✓" if d.ok else "✗"
            click.echo(f"  [{status}] {d.directory}: {d.message}"
                       f"{f' (HTTP {d.status_code})' if d.status_code else ''}")
        click.echo("")
        click.echo(result.manual_checklist)

    sys.exit(0)


@main.command()
@click.argument("repo", type=click.Path(exists=True, file_okay=False, path_type=Path))
def checklist(repo: Path) -> None:
    """Print the manual directory submission checklist for REPO."""
    click.echo(render_checklist(Path(repo).name))


@main.command()
@click.argument("repo", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--network", is_flag=True, default=False,
              help="Enable 3 network probes (GHCR, Smithery, MCP Registry).")
@click.option("--force", is_flag=True, default=False,
              help="Skip the audit gate (publish even if score < 80).")
def all(repo: Path, network: bool, force: bool) -> None:
    """audit + cross-post + checklist, in that order."""
    if network:
        os.environ["MEOK_ALLOW_NETWORK"] = "1"

    # 1) audit
    sc = audit_score(repo, allow_network=network)
    click.echo(sc.to_markdown())
    click.echo("")

    # 2) gate
    if sc.gate.value == "block" and not force:
        click.echo("BLOCK — refusing to cross-post. Re-run with --force to override.",
                   err=True)
        sys.exit(1)

    if sc.gate.value == "review" and not force:
        click.echo("REVIEW — proceeding with --force implied (gate verdict was review).")

    # 3) cross-post
    result = cross_post_run(repo)
    if not result.preflight_ok:
        click.echo("Pre-flight FAILED — refusing to publish inconsistent metadata:",
                   err=True)
        for e in result.preflight_errors:
            click.echo(f"  - {e}", err=True)
        sys.exit(1)

    click.echo("=== Cross-post results ===")
    for d in result.directories:
        status = "✓" if d.ok else "✗"
        click.echo(f"  [{status}] {d.directory}: {d.message}"
                   f"{f' (HTTP {d.status_code})' if d.status_code else ''}")
    click.echo("")

    # 4) manual checklist
    click.echo(result.manual_checklist)

    sys.exit(0)


def _do_cross_post(repo: Path) -> None:
    """Run cross_post and print its results (shared by refine/fleet)."""
    result = cross_post_run(repo)
    if not result.preflight_ok:
        click.echo("Pre-flight FAILED — refusing to publish inconsistent metadata:",
                   err=True)
        for e in result.preflight_errors:
            click.echo(f"  - {e}", err=True)
        sys.exit(1)
    click.echo("=== Cross-post results ===")
    for d in result.directories:
        status = "✓" if d.ok else "✗"
        click.echo(f"  [{status}] {d.directory}: {d.message}"
                   f"{f' (HTTP {d.status_code})' if d.status_code else ''}")
    click.echo("")
    click.echo(result.manual_checklist)


@main.command()
@click.argument("repo", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--scaffold", "do_scaffold", is_flag=True, default=False,
              help="Create the SAFE missing static discovery files, then re-audit. "
                   "Never writes server.py or runs repo code.")
@click.option("--no-post", is_flag=True, default=False,
              help="Audit/refine only — never cross-post even if the gate passes.")
@click.option("--allow-network", is_flag=True, default=False,
              help="Enable the 3 network probes during the audit.")
def refine(repo: Path, do_scaffold: bool, no_post: bool, allow_network: bool) -> None:
    """Audit REPO, print a gap report, optionally scaffold + re-audit, then gate.

    The loop: audit → if MERGE report ready (and cross-post unless --no-post);
    else print a precise GAP REPORT. With --scaffold, create the safe missing
    static discovery files, re-audit, print the new score, and cross-post if it
    now passes (unless --no-post).
    """
    if allow_network:
        os.environ["MEOK_ALLOW_NETWORK"] = "1"

    sc = audit_score(repo, allow_network=allow_network)
    click.echo(sc.to_markdown())
    click.echo("")

    if sc.gate.value == "merge":
        click.echo(f"✓ {sc.repo_name} is READY (gate=MERGE, {sc.total_points}/{sc.eligible_points}).")
        if not no_post:
            click.echo("")
            _do_cross_post(repo)
        sys.exit(0)

    # Below the gate — show the actionable gap report.
    click.echo(gap_report(sc))

    if not do_scaffold:
        click.echo("")
        click.echo("Re-run with --scaffold to auto-create the SAFE missing discovery files "
                   "(smithery.yaml, server.json, .well-known/mcp/server-card.json, "
                   "package.json, glama.json, SECURITY.md).", err=True)
        sys.exit(1)

    # Scaffold the safe static files, then re-audit.
    written = scaffold_mod.scaffold(repo)
    click.echo("")
    if written:
        click.echo("=== Scaffolded safe discovery files ===")
        for rel in written:
            click.echo(f"  + {rel}")
    else:
        click.echo("No missing scaffoldable files — nothing to create.")
    click.echo("")

    sc2 = audit_score(repo, allow_network=allow_network)
    click.echo("=== Re-audit after scaffold ===")
    click.echo(sc2.to_markdown())
    click.echo("")

    if sc2.gate.value == "merge":
        click.echo(f"✓ {sc2.repo_name} now PASSES (gate=MERGE, "
                   f"{sc2.total_points}/{sc2.eligible_points}).")
        if not no_post:
            click.echo("")
            _do_cross_post(repo)
        sys.exit(0)

    click.echo(gap_report(sc2))
    click.echo("")
    click.echo("Still below the merge gate after scaffold — the remaining gaps need "
               "server.py / CI work (not auto-scaffoldable).", err=True)
    sys.exit(1)


@main.command()
@click.argument("paths", nargs=-1,
                type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True, default=False,
              help="Emit a machine-readable JSON scoreboard.")
@click.option("--threshold", type=int, default=80,
              help="Override the pass gate for the summary count. Default: 80.")
@click.option("--allow-network", is_flag=True, default=False,
              help="Enable the 3 network probes during each audit.")
def fleet(paths: tuple, as_json: bool, threshold: int, allow_network: bool) -> None:
    """Audit many repos (PATHS) into one ranked scoreboard.

    With no PATHS, globs the immediate subdirectories of the current dir that
    contain a pyproject.toml. Audits run in parallel. Prints a markdown table
    (repo | score | gate | top failing category) sorted by score desc, plus a
    summary line. Use --json for machine-readable output.
    """
    if allow_network:
        os.environ["MEOK_ALLOW_NETWORK"] = "1"

    repos = list(paths) if paths else fleet_mod.discover_repos(Path.cwd())
    if not repos:
        click.echo("No repos found (no PATHS given and no ./*/pyproject.toml).", err=True)
        sys.exit(1)

    cards = fleet_mod.audit_many(repos, allow_network=allow_network)

    if as_json:
        click.echo(json.dumps(fleet_mod.scoreboard_json(cards, threshold=threshold), indent=2))
    else:
        click.echo(fleet_mod.scoreboard_markdown(cards, threshold=threshold))
    sys.exit(0)


@main.group()
def auth() -> None:
    """One-time auth setup (GitHub PAT → keyring)."""


@auth.command("bootstrap")
@click.option("--token", default=None,
              help="GitHub PAT (or paste interactively). Needs `repo` + `read:org` scopes.")
def auth_bootstrap(token: str) -> None:
    """Store a GitHub PAT in the OS keychain for MCP Registry JWT exchange.

    The token needs `repo` and `read:org` scopes so the JWT exchange
    can prove ownership of the io.github.CSOAI-ORG namespace.
    """
    if not token:
        token = click.prompt("GitHub PAT", hide_input=True, confirmation_prompt=False)

    if not token or len(token) < 20:
        click.echo("Token looks too short. Expected a GitHub PAT (40+ chars).", err=True)
        sys.exit(1)

    try:
        import keyring
    except ImportError:
        click.echo("`keyring` package not installed. Run: pip install keyring", err=True)
        sys.exit(1)

    try:
        keyring.set_password("meok-cross-post", "github-pat", token)
        click.echo("✓ Stored GitHub PAT in OS keychain under 'meok-cross-post' / 'github-pat'.")
        click.echo("  Future `meok-cross-post cross-post` runs will use it automatically.")
    except Exception as e:
        click.echo(f"Keyring write failed: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

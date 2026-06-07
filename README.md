# meok-cross-post (openMCP)

**One CLI to audit a flagship MCP server and cross-post it to every top directory.**

`meok-cross-post` is the keystone tool for the MEOK fleet's directory presence — the discovery layer for the MEOK **EU AI Act / DORA / NIS2 / CRA** compliance servers. It scores a flagship MCP repo 0–100 against the [FLEET_BASE.md](https://github.com/CSOAI-ORG/meok-compliance-gateway/blob/main/FLEET_BASE.md) template, and pushes its metadata to the directories that have public APIs. For the directories that don't, it prints a clean manual checklist and exits 0. 82 tests passing, Apache-2.0.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

## Why

The 290 repos in `CSOAI-ORG` need to be discoverable on Smithery, MCP Registry, Docker MCP Catalog, Glama, MCPize, and PulseMCP. Today that discoverability is hand-rolled — a separate workflow per directory, a separate visibility-flip per registry. Doing it once is tedious. Doing it 290 times is impossible without a tool.

`meok-cross-post` does it in one shot:

```
$ meok-cross-post all ../threat-intelligence

[1/3] AUDIT
  Score:     100/100 (PASS — meets merge gate ≥ 80)
  Category:  A 25/25  B 25/25  C 25/25  D 15/15  E 10/10

[2/3] CROSS-POST
  Smithery:        PUT /servers/nicholastempleman%2Fthreat-intelligence-mcp  201 Created
  MCP Registry:    POST /v0/publish  201 Created
  (Both idempotent — re-run returns 200 / 409-success.)

[3/3] MANUAL CHECKLIST
  [ ] Docker MCP Catalog: open PR at https://github.com/docker/mcp-registry/new
      File: servers/threat-intelligence.yaml (template: /tmp/meok-cross-post/threat-intelligence-docker-catalog.yaml)
  [ ] Glama:              visit https://glama.ai/mcp/servers → click "Add Server" → paste
                          https://github.com/CSOAI-ORG/threat-intelligence
  [ ] MCPize:             visit https://mcpize.com/developer/servers/new (or `npm i -g mcpize && mcpize deploy`)
  [ ] PulseMCP:           visit https://www.pulsemcp.com/submit
```

## Install

```bash
pip install meok-cross-post
```

## Usage

### Audit only (no network calls)

```bash
meok-cross-post audit /path/to/flagship                    # markdown table
meok-cross-post audit /path/to/flagship --format json      # JSON for CI / dashboards
meok-cross-post audit /path/to/flagship --network          # adds GHCR + Smithery + MCP Registry probes
```

The audit scorecard is a 100-pt rubric across 5 categories:

| Category | Pts | What it checks |
|---|---:|---|
| A. Package installability | 25 | pyproject.toml, hatchling backend, only-include=[server.py], mcp>=1.0.0, scripts entry, wheel builds |
| B. Server correctness | 25 | server.py imports, mcp object declared, ≥3 tools, all tools docstringed, auth_middleware.py, real test file |
| C. Discovery & directories | 25 | smithery.yaml (declarative, no `runtime:`), server.json, server-card.json, glama.json, package.json |
| D. Distribution & ops | 15 | Dockerfile.glama, mcp-wrapper.py, GHCR image public, listed on Smithery, listed on MCP Registry |
| E. CI/CD & docs | 10 | test.yml + ci.yml + mcp-smithery-publish.yml, README has install + features + license, SECURITY.md |

**Merge gate:** total ≥ 80 AND every per-category minimum satisfied. Empty shells (`.gitignore + LICENSE + README.md + package.json` only) score ≤ 4/100 → BLOCK.

### Cross-post only

```bash
meok-cross-post cross-post /path/to/flagship
```

Pushes to the two automatable directories (Smithery + MCP Registry) **concurrently** — they hit different APIs with no ordering dependency, so the directory pushes fan out in parallel (a failure in one never aborts the other). For the other four directories, prints the manual checklist.

### Manual checklist only

```bash
meok-cross-post checklist /path/to/flagship
```

### All-in-one

```bash
meok-cross-post all /path/to/flagship            # audit → cross-post → checklist
meok-cross-post all /path/to/flagship --force     # skip the score gate
```

### Refine — audit → gap-report → (scaffold) → re-audit → gate → cross-post

`refine` codifies the manual remediation loop. It audits the repo; if it already meets the merge gate it reports "ready" and (unless `--no-post`) cross-posts. Otherwise it prints a precise **gap report** — for every failed/low check, the check id, what's missing, and the exact remediation — grouped by category.

```bash
meok-cross-post refine /path/to/flagship                 # audit + gap report (exit 1 if below gate)
meok-cross-post refine /path/to/flagship --no-post        # never cross-post, even if it passes
meok-cross-post refine /path/to/flagship --scaffold       # create the SAFE missing files, re-audit, then post
meok-cross-post refine /path/to/flagship --allow-network  # include the 3 network probes
```

`--scaffold` creates **only** the safe static discovery files that are missing — `smithery.yaml`, `server.json`, `.well-known/mcp/server-card.json`, `package.json`, `glama.json`, `SECURITY.md` — derived from the repo's `pyproject.toml` (name/description/version) and the `@mcp.tool` functions in `server.py`. It **never** writes `server.py` and **never** executes repo code. After scaffolding it re-audits, prints the new score, and (if it now passes and not `--no-post`) cross-posts.

### Fleet — one scoreboard for many repos

`fleet` audits many repos in parallel and prints one ranked markdown scoreboard: which repos are ready to blast.

```bash
meok-cross-post fleet                                # globs ./*/pyproject.toml subdirs
meok-cross-post fleet ../repo-a ../repo-b            # explicit paths
meok-cross-post fleet --json                          # machine-readable
meok-cross-post fleet --threshold 90                  # override the pass gate for the summary
```

```
| Repo | Score | Gate | Top failing category |
|---|---|---|---|
| threat-intelligence | 100 | 🟢 | D_distribution |
| bare-thing          |  12 | 🔴 | B_server |

**2 repos, 1 passing (MERGE, score ≥ 80), mean score 56.0.**
```

### One-time auth setup

```bash
meok-cross-post auth bootstrap      # GitHub PAT → keyring (for MCP Registry JWT exchange)
```

## As an MCP server

`meok-cross-post` also ships a 50-line MCP shim. It exposes 3 tools over streamable-HTTP, so any MCP-aware agent can drive it:

| Tool | Description |
|---|---|
| `audit_repo` | Score an MCP server repo 0–100 against the openMCP listing-readiness rubric; returns a merge/block verdict + per-category breakdown. **Read-only.** |
| `cross_post_metadata` | Push a repo's metadata to Smithery and the MCP Registry (the two directories with public APIs); returns per-directory results. |
| `manual_checklist` | Return the manual submission checklist as markdown for directories without a public API (Docker MCP Catalog, Glama, MCPize, PulseMCP). **Read-only.** |

```bash
openmcp                                     # starts the shim on $PORT (default 8000)
```

Or import it into your own FastMCP server:

```python
from meok_cross_post import audit, cross_post, manual_checklist
# All three are plain Python functions; the shim is a thin wrapper.
```

## Design

- **CLI-primary, MCP-secondary** — the actual work is "read a repo, call REST APIs, print output." That's a CLI. The MCP shim is a 50-line sibling, not a wrapper.
- **smithery.yaml is the source of truth** — the cross-post pre-flight reads `smithery.yaml`, `server.json`, `glama.json`, `server-card.json`, and `package.json`, asserts they agree on `<name>` + tool list, and refuses to post inconsistent metadata.
- **Manual-checklist directories are not faked** — Docker Catalog, Glama, MCPize, PulseMCP have no public API. The CLI prints the exact URL and (for Docker) the file the user needs to add. This is more useful than a half-working scrape.
- **Network probes are off the PR hot path** — `audit <path>` is local-only by default (used in PR CI). `--network` enables 3 probes (GHCR, Smithery, MCP Registry) and is used in the monthly cron.

## Reference

- [meok-compliance-gateway](https://github.com/CSOAI-ORG/meok-compliance-gateway) — the keystone gateway; the rubric comes from its `FLEET_BASE.md`
- [Model Context Protocol Registry](https://registry.modelcontextprotocol.io) — the canonical directory
- [Smithery](https://smithery.ai) — `PUT /servers/<ns>/<name>` for the display card
- [Docker MCP Catalog](https://github.com/docker/mcp-registry) — `servers/<name>.yaml` PR

## License

Apache-2.0. See [LICENSE](LICENSE).

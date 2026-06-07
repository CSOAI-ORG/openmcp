# DISTRIBUTION.md — list openMCP (meok-cross-post) everywhere

The complete "list it everywhere" submission checklist for **openMCP** (`meok-cross-post`).
openMCP is the tool that automates this for *other* repos — and it can cross-post **itself**.
Each entry has the exact submission URL, what it needs, the prepared payload, and whether
openMCP's own `cross-post` CLI can automate it.

**Gating legend**
- **UNGATED-READY** — payload prepared; submit the moment publishing unblocks.
- **GATED-ON-PUBLISH** — blocked until the PyPI package and/or a public GHCR image and/or the
  public GitHub repo exists.

**Canonical metadata (single source of truth — keep all directories consistent):**
- Name: `meok-cross-post` (a.k.a. openMCP; namespace `io.github.csoai-org/meok-cross-post`)
- Description: *Audit + cross-post flagship MCP servers to Smithery, MCP Registry, Docker Catalog, Glama, MCPize, PulseMCP — one CLI for the whole directory ecosystem.*
- Repo: https://github.com/CSOAI-ORG/meok-cross-post
- Homepage: https://github.com/CSOAI-ORG/meok-cross-post (web/ landing page placeholder host: openmcp.dev — confirm)
- License: Apache-2.0 (declared in pyproject.toml / package.json / server.json). **NOTE:** the repo's `LICENSE` file currently contains the MIT text — reconcile to Apache-2.0 before publishing so the listings and the LICENSE file agree.
- PyPI: `meok-cross-post`
- Transport: streamable-http; tools: `audit_repo`, `cross_post_metadata`, `manual_checklist`

---

## What openMCP's own tooling produces (captured)

`python -m meok_cross_post.cli --help`:
```
Commands:
  all         audit + cross-post + checklist, in that order.
  audit       Score REPO 0-100 against FLEET_BASE.md.
  auth        One-time auth setup (GitHub PAT → keyring).
  checklist   Print the manual directory submission checklist for REPO.
  cross-post  Push REPO's metadata to Smithery + MCP Registry.
```

`python -m meok_cross_post.cli cross-post --help`:
```
Usage: ... cross-post [OPTIONS] REPO
  Push REPO's metadata to Smithery + MCP Registry.
  Prints the result for each directory (or skips with a hint if the required
  env var is missing). Always prints the manual checklist at the end for the 4
  directories without public APIs.
Options:
  --format [text|json]
```

`python -m meok_cross_post.cli checklist /Users/nicholas/meok-cross-post` (verbatim):
```
=== Manual directory submissions for meok-cross-post ===

[ ] **Docker MCP Catalog** — Fork docker/mcp-registry, add `servers/meok-cross-post.yaml`, open PR
    URL: https://github.com/docker/mcp-registry/new
    Note: ~24h SLA. Template generated below; copy it into your fork.

[ ] **Glama** — Click 'Add Server' → paste your repo URL
    URL: https://glama.ai/mcp/servers
    Note: Your glama.json should already claim CSOAI-ORG as maintainer. If not, edit the file in your repo first.

[ ] **MCPize** — Open the form, paste repo URL + description. Or `npm i -g mcpize && mcpize deploy` from the repo.
    URL: https://mcpize.com/developer/servers/new
    Note: Flip visibility to public in the dashboard after deploy.

[ ] **PulseMCP** — One form, ~2 minutes. Paste repo URL + description.
    URL: https://www.pulsemcp.com/submit
```

So openMCP's `cross-post` automates exactly **two** directories (Smithery + MCP Registry) and
emits the manual checklist above for the **four** API-less ones. The sections below extend that
to the full "everywhere" set.

---

## 0. PyPI (the foundational gate)

- **URL:** https://upload.pypi.org/legacy/ (via `twine upload dist/*`)
- **Needs:** a PyPI account + token for `meok-cross-post`. Wheel/sdist already in `dist/`.
- **Payload:** read from `pyproject.toml` (name, version 0.1.0, Apache-2.0, keywords, classifiers).
- **Automatable via openMCP?** No — openMCP lists directories, it does not publish to PyPI.
- **Gate status:** **GATED-ON-PUBLISH** — this is the gate most others depend on.
- **Command:** `python -m twine upload dist/*`

---

## 1. MCP Registry (registry.modelcontextprotocol.io)

- **URL:** https://registry.modelcontextprotocol.io → `POST /v0/publish`
- **Needs:** GitHub PAT → JWT (run `meok-cross-post auth bootstrap` once); PyPI package should exist. `server.json` present.
- **Payload:** repo `server.json` (`io.github.csoai-org/meok-cross-post`, pypi `meok-cross-post`, streamable-http).
- **Automatable via openMCP?** **Yes** — `meok-cross-post cross-post .`.
- **Gate status:** **GATED-ON-PUBLISH** (PyPI publish + repo public).

---

## 2. Smithery (smithery.ai)

- **URL:** https://smithery.ai → `PUT /servers/<namespace>/<name>`. Manual fallback: https://smithery.ai/new
- **Needs:** Smithery account / API key. `smithery.yaml` present (declarative, no `runtime:`, 3 tools, displayName "openMCP").
- **Payload:** repo `smithery.yaml`.
- **Automatable via openMCP?** **Yes** — `meok-cross-post cross-post .`.
- **Gate status:** **GATED-ON-PUBLISH** (repo public + Smithery key).

---

## 3. Glama (glama.ai)

- **URL:** https://glama.ai/mcp/servers → "Add Server" → paste `https://github.com/CSOAI-ORG/meok-cross-post`
- **Needs:** public repo; `glama.json` claims CSOAI-ORG as maintainer. No public API.
- **Payload:** repo URL + canonical description.
- **Automatable via openMCP?** No — emitted as a manual checklist line.
- **Gate status:** **GATED-ON-PUBLISH** (repo public).

---

## 4. MCPize (mcpize.com)

- **URL:** https://mcpize.com/developer/servers/new (or `npm i -g mcpize && mcpize deploy`)
- **Needs:** MCPize account; flip visibility to public after deploy.
- **Payload:** repo URL + canonical description + 3 tools.
- **Automatable via openMCP?** No — manual checklist line.
- **Gate status:** **GATED-ON-PUBLISH** (repo public / account).

---

## 5. PulseMCP (pulsemcp.com)

- **URL:** https://www.pulsemcp.com/submit
- **Needs:** public repo; single ~2-minute form.
- **Payload:** repo URL + canonical description.
- **Automatable via openMCP?** No — manual checklist line.
- **Gate status:** **GATED-ON-PUBLISH** (repo public).

---

## 6. Docker MCP Catalog (docker/mcp-registry)

- **URL:** https://github.com/docker/mcp-registry/new → PR adding `servers/meok-cross-post.yaml`
- **Needs:** public GHCR image (built from `Dockerfile.glama`) + a GitHub PR. ~24h SLA.
- **Payload:** `servers/meok-cross-post.yaml` (name, description, image ref, 3 tools). openMCP generates this YAML template.
- **Automatable via openMCP?** Partial — generates the YAML; the PR is manual.
- **Gate status:** **GATED-ON-PUBLISH** (public GHCR image + repo public).

---

## 7. mcp.so

- **URL:** https://mcp.so/submit
- **Needs:** public repo; web form. Also auto-indexes from the MCP Registry, so #1 may cover it.
- **Payload:** repo URL + canonical description + tool list.
- **Automatable via openMCP?** No (not in the cross-post target set) — manual.
- **Gate status:** **GATED-ON-PUBLISH** (repo public).

---

## 8. GitHub Topics

- **URL:** repo → About → ⚙ Topics (https://github.com/CSOAI-ORG/meok-cross-post)
- **Needs:** repo public + write access.
- **Payload (topics to add):** `mcp`, `model-context-protocol`, `smithery`, `glama`, `mcpize`, `pulsemcp`, `mcp-registry`, `docker-mcp-catalog`, `cli`, `scorecard`, `audit`, `openmcp`.
- **Automatable via openMCP?** No — manual (GitHub UI / `gh api`).
- **Gate status:** **GATED-ON-PUBLISH** (repo public). *Topic strings are UNGATED-READY to paste.*

---

## 9. awesome-mcp-servers lists (community PRs)

- **URLs:** https://github.com/punkpeye/awesome-mcp-servers , https://github.com/wong2/awesome-mcp-servers , https://github.com/appcypher/awesome-mcp-servers
- **Needs:** public repo; a PR per list under the right category (likely "Tools / Developer Tools").
- **Payload (list line):**
  `- [meok-cross-post (openMCP)](https://github.com/CSOAI-ORG/meok-cross-post) — Audit any MCP server on a 100-point rubric and cross-post it to Smithery, Glama, MCPize, PulseMCP, the MCP Registry, and the Docker MCP Catalog from one CLI.`
- **Automatable via openMCP?** No — manual PRs.
- **Gate status:** **GATED-ON-PUBLISH** (repo public).

---

## Summary

| # | Directory | Automatable via openMCP | Gate |
|--:|-----------|:-----------------------:|------|
| 0 | PyPI | No | GATED-ON-PUBLISH |
| 1 | MCP Registry | Yes | GATED-ON-PUBLISH |
| 2 | Smithery | Yes | GATED-ON-PUBLISH |
| 3 | Glama | No | GATED-ON-PUBLISH |
| 4 | MCPize | No | GATED-ON-PUBLISH |
| 5 | PulseMCP | No | GATED-ON-PUBLISH |
| 6 | Docker MCP Catalog | Partial | GATED-ON-PUBLISH |
| 7 | mcp.so | No | GATED-ON-PUBLISH |
| 8 | GitHub Topics | No | GATED-ON-PUBLISH |
| 9 | awesome-mcp-servers | No | GATED-ON-PUBLISH |

**Total directories: 10.** Every payload above is **prepared and UNGATED-READY to paste**, but
each *submission* is **GATED-ON-PUBLISH** because all require at least the public GitHub repo
(and usually PyPI and/or a public GHCR image). Once PyPI publish + repo-public clear, 3 are
automatable (MCP Registry, Smithery fully; Docker catalog YAML partially) via openMCP's own
`meok-cross-post cross-post .`; the rest are manual web forms / PRs with the payloads above.

**Pre-publish action:** reconcile the `LICENSE` file (currently MIT text) to Apache-2.0 to match
all declared metadata.

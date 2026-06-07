"""meok-cross-post — audit + cross-post flagship MCP servers to all top directories.

This package is the keystone tool for the MEOK fleet's directory presence.
It runs a 100-point scorecard against any flagship MCP repo (matching
FLEET_BASE.md) and cross-posts its metadata to:

  Automatable (REST API):
    - Smithery:           PUT https://api.smithery.ai/servers/<ns>%2F<name>
    - MCP Registry:       POST https://registry.modelcontextprotocol.io/v0/publish

  Manual checklist (printed, exit 0):
    - Docker MCP Catalog: github.com/docker/mcp-registry PR
    - Glama:              glama.ai "Add Server" form
    - MCPize:             mcpize.com/developer dashboard
    - PulseMCP:           pulsemcp.com/submit form

CLI:    meok-cross-post {audit,cross-post,refine,fleet,checklist,all,auth} <path>
MCP:    python -m meok_cross_post.mcp_server  (3 @mcp.tool() shim)

`refine` runs the audit→gap-report→(scaffold)→re-audit→gate→cross-post loop
for one repo; `fleet` audits many repos in parallel into one ranked scoreboard.
"""

__version__ = "0.1.0"
__all__ = ["__version__"]

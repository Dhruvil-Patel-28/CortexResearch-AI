"""
FastMCP server — stdio transport wrapper over `mcp_server.tools`.

Run standalone:
    python -m mcp_server.server

Register in an MCP client (e.g. Claude Desktop):
    {
      "mcpServers": {
        "cortexresearch": {
          "command": "/path/to/.venv/bin/python",
          "args": ["-m", "mcp_server.server"]
        }
      }
    }
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_server import tools


def build_server() -> FastMCP:
    """Build the FastMCP instance with all tools registered."""
    mcp: FastMCP = FastMCP("cortexresearch")

    @mcp.tool()
    def search_library(query: str, k: int = 8) -> dict[str, Any]:
        """Hybrid (BM25 + dense) retrieval over your saved corpus of items and reports; adds a knowledge-graph answer when GraphRAG is enabled."""
        return tools.search_library(query, k=k)

    @mcp.tool()
    def list_reports(limit: int = 20) -> list[dict[str, Any]]:
        """List published research reports, newest first."""
        return tools.list_reports(limit=limit)

    @mcp.tool()
    def get_report(report_id: str) -> dict[str, Any] | None:
        """Fetch one full research report (schema-v2 JSON) by id."""
        return tools.get_report(report_id)

    @mcp.tool()
    def list_items(since_hours: int = 24, limit: int = 50) -> list[dict[str, Any]]:
        """Recent pulse-feed items (newest first) with relevance scores and 'why this matters' rationale."""
        return tools.list_items(since_hours=since_hours, limit=limit)

    @mcp.tool()
    def get_item(item_id: str) -> dict[str, Any] | None:
        """Fetch one pulse item with full text and score rationale."""
        return tools.get_item(item_id)

    @mcp.tool()
    def start_research(query: str, depth: str = "brief") -> dict[str, Any]:
        """Start a multi-agent research run (planner → parallel researchers → verifier → writer); returns a job id immediately."""
        return tools.start_research(query, depth=depth)

    @mcp.tool()
    def get_research(job_id: str) -> dict[str, Any]:
        """Poll a research job; includes a report summary (title, TLDR, sources) when finished."""
        return tools.get_research(job_id)

    return mcp


def main() -> None:
    """Entry point: serve over stdio (blocks until the client disconnects)."""
    build_server().run()


if __name__ == "__main__":
    main()

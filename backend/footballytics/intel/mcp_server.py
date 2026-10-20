"""Football Intelligence MCP server.

Exposes the same tools our agents use to any MCP client (GitHub Copilot agent mode, Claude,
Foundry agents) over streamable HTTP. Mounted at ``/mcp`` inside the API app; can also run
standalone over stdio for local IDE use:  python -m footballytics.intel.mcp_server --stdio
"""

from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP

from . import tools

INSTRUCTIONS = (
    "Live, explainable intelligence for synthetic football matches (a fictional league). "
    "Start with list_live_matches, then get_match_state / get_moments. Use explain_moment to see the evidence "
    "behind a moment and verify_claims to fact-check numbers before stating them. Player ids look like 'RIV-09'."
)


def build(stateless: bool = True) -> FastMCP:
    server = FastMCP("footballytics", instructions=INSTRUCTIONS, stateless_http=stateless, json_response=True)
    for fn in tools.TOOLS:
        server.add_tool(fn, name=fn.__name__, description=(fn.__doc__ or "").strip())
    return server


if __name__ == "__main__":
    if "--stdio" in sys.argv:
        import asyncio

        from ..hub import LiveHub

        async def main() -> None:
            hub = LiveHub()
            hub.load_matchday(int(sys.argv[sys.argv.index("--md") + 1]) if "--md" in sys.argv else 9)
            tools.bind(hub)
            hub.start(speed=10.0)
            await build(stateless=False).run_stdio_async()

        asyncio.run(main())

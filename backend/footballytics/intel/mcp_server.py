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


def transport_security():
    """DNS-rebinding protection stays on; public hostnames are allow-listed via MCP_ALLOWED_HOSTS
    (comma-separated, e.g. the Container Apps FQDN). Local development hosts are always allowed."""
    import os

    from mcp.server.transport_security import TransportSecuritySettings

    hosts = ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*"]
    hosts += [h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    origins = ["http://localhost:*", "http://127.0.0.1:*"] + [f"https://{h}" for h in hosts if "localhost" not in h
                                                               and "127.0.0.1" not in h]
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts,
                                     allowed_origins=origins)


def build(stateless: bool = True) -> FastMCP:
    server = FastMCP("footballytics", instructions=INSTRUCTIONS, stateless_http=stateless, json_response=True,
                     transport_security=transport_security())
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

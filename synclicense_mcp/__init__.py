"""Sync Licensing MCP server.

A local Model Context Protocol server for a music sync-licensing platform.
The MCP message flow is implemented directly on top of JSON-RPC 2.0; no MCP
SDK is used anywhere in this package.
"""

__version__ = "0.1.0"

SERVER_NAME = "synclicense-mcp"

# MCP revisions this server knows how to speak, most recent first.
SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18")
PREFERRED_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]

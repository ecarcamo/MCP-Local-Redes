"""Entry point: ``python -m synclicense_mcp``.

Starts the MCP server on the stdio transport. Protocol traffic goes over
stdin/stdout; diagnostics go to stderr.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .catalog import CatalogoNoEncontrado, cargar_catalogo
from .jsonrpc import log
from .server import Servidor


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m synclicense_mcp",
        description="Sync Licensing MCP server (stdio transport, JSON-RPC 2.0).",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="path to the catalog JSON (default: data/catalog.json)",
    )
    args = parser.parse_args()

    try:
        catalogo = cargar_catalogo(args.catalog)
    except CatalogoNoEncontrado as exc:
        log(str(exc))
        return 1

    # Reconfigure the streams so the transport is UTF-8 and line-buffered
    # regardless of the host's locale.
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")

    Servidor(catalogo).ejecutar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

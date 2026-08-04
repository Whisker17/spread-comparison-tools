"""Entrypoint for spread-comparison-tools.

- Startup validates the app factory (and later: config/secrets) and fails fast.
- ``--dry-run`` never starts a server and never touches the network.
"""

from __future__ import annotations

import argparse


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="spread-comparison-tools")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration and exit without starting the server",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host when starting the server (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Bind port when starting the server (default: 8000)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Load .env before any adapter reads required secrets (AGENTS.md runtime config).
    from dotenv import load_dotenv

    load_dotenv()

    # Import here so --help stays cheap and dry-run still exercises app construction.
    from spread_compare.api.app import create_app
    from spread_compare.fees import get_fee_catalog
    from spread_compare.settings import (
        load_aggregator_settings,
        load_impact_settings,
        load_mid_settings,
    )

    # Fail-fast typed config (including fee YAML) without starting the server.
    load_mid_settings()
    load_aggregator_settings()
    load_impact_settings()
    get_fee_catalog()

    app = create_app()

    if args.dry_run:
        route_paths = sorted({getattr(r, "path", "") for r in app.routes} - {""})
        print(f"spread-comparison-tools dry-run ok (routes={route_paths})")
        return 0

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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

    # Import here so --help stays cheap and dry-run still exercises app construction.
    from spread_compare.api.app import create_app

    app = create_app()

    if args.dry_run:
        print(
            "spread-comparison-tools dry-run ok "
            f"(routes={[r.path for r in app.routes if hasattr(r, 'path')]})"
        )
        return 0

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

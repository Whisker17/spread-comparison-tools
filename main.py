"""Entrypoint for spread-comparison-tools.

Deliberately minimal: the template ships no runtime framework. Replace the body as the
first implementation issues land (per docs/DESIGN.md §4.4), keeping two properties:

- Startup validates configuration/secrets and fails fast with a clear error.
- `--dry-run` never performs external side effects.
"""

import argparse


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="spread-comparison-tools")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mode = "dry-run" if args.dry_run else "live"
    print(f"spread-comparison-tools skeleton ready ({mode}); implement per docs/DESIGN.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

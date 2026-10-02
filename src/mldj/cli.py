"""mldj command line.

build_parser() owns the top-level parser; each feature module registers its own
subcommand so no single file has to know about all of them.
"""

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    from mldj import candidates, capture, export, live, playlist, scrobbles, tags
    from mldj.measure import report
    from mldj.space import evaluate

    parser = argparse.ArgumentParser(prog="mldj", description="ml-dj offline tools")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    capture.register(subparsers)
    scrobbles.register(subparsers)
    report.register(subparsers)
    tags.register(subparsers)
    evaluate.register(subparsers)
    export.register(subparsers)
    candidates.register(subparsers)
    live.register(subparsers)
    playlist.register(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if not args.command or handler is None:
        parser.print_usage()
        return 2
    return int(handler(args))

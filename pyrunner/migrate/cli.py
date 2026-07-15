"""CLI: python -m pyrunner.migrate <paths> [--write] [--no-diff] [--report FILE]"""

import argparse
import sys
from pathlib import Path

from .runner import migrate_paths, render_diffs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pyrunner.migrate",
        description="Migrate pytest test suites to pyrunner. Dry-run by "
        "default: shows diffs and a report, changes nothing.",
    )
    parser.add_argument("paths", nargs="+", help="test directories and/or .py files")
    parser.add_argument(
        "--write", action="store_true", help="apply changes in place (use git for rollback)"
    )
    parser.add_argument(
        "--no-diff", action="store_true", help="suppress unified diffs (summary only)"
    )
    parser.add_argument(
        "--report", metavar="FILE", help="also write the report as markdown to FILE"
    )
    parser.add_argument(
        "--case-id-marker",
        metavar="NAME",
        default="test_case_id",
        help="pytest marker whose string argument becomes @test(case_id=...) "
        "(default: test_case_id; pass an empty string to disable)",
    )
    parser.add_argument(
        "--no-config",
        action="store_true",
        help="skip generating pyrunner.toml from pyproject.toml "
        "[tool.pytest.ini_options]",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    for raw in args.paths:
        if not Path(raw).exists():
            print(f"error: path does not exist: {raw}", file=sys.stderr)
            return 2

    report, changes = migrate_paths(
        args.paths,
        write=args.write,
        case_id_marker=args.case_id_marker,
        migrate_config_files=not args.no_config,
    )

    if changes and not args.no_diff and not args.write:
        print(render_diffs(changes))
    print(report.render_console(wrote=args.write))

    if args.report:
        Path(args.report).write_text(report.render_markdown(wrote=args.write), encoding="utf-8")
        print(f"\nmarkdown report written to {args.report}")

    if any(f.error for f in report.files):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

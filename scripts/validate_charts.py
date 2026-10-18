#!/usr/bin/env python3
"""
Validate every strategy chart. Run by CI and by `make validate-charts`.

    python scripts/validate_charts.py [charts_dir] [--strict] [--no-baseline]

Errors fail the run unless they are listed in CHART_KNOWN_ISSUES.json. A baseline
entry that no longer fires also fails the run, so fixing a chart forces the entry
to be deleted. `--strict` additionally fails on warnings.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from logic.chart_schema import (  # noqa: E402
    DEFAULT_BASELINE,
    ERROR,
    WARNING,
    apply_baseline,
    load_baseline,
    load_charts,
)


def _print_grouped(issues, verbose: bool) -> None:
    """One line per issue code, so a problem shared by all 52 charts reads as one problem."""
    by_code: dict[str, list] = {}
    for issue in issues:
        by_code.setdefault(issue.code, []).append(issue)

    for code, group in sorted(by_code.items()):
        if len(group) == 1 or verbose:
            for issue in group:
                print(f"  {issue}")
        else:
            print(f"  [WARNING] {code} - {len(group)} charts: {group[0].message}")
            print("            (run with -v to list them)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", default="strategy_charts")
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--no-baseline", action="store_true", help="report known issues as failures too")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    parser.add_argument("-v", "--verbose", action="store_true", help="list every chart behind a warning")
    args = parser.parse_args()

    charts, issues = load_charts(args.directory)
    baseline = set() if args.no_baseline else load_baseline(args.baseline)
    result = apply_baseline(issues, baseline)

    new_errors = [i for i in result.new if i.severity == ERROR]
    new_warnings = [i for i in result.new if i.severity == WARNING]

    if new_errors:
        print("Errors:")
        for issue in new_errors:
            print(f"  {issue}")
    if new_warnings:
        print("\nWarnings:")
        _print_grouped(new_warnings, verbose=args.verbose)
    if result.known:
        print(f"\nKnown issues (see CHART_KNOWN_ISSUES.json): {len(result.known)} suppressed")
    if result.stale:
        print("\nStale baseline entries - these no longer occur and must be removed:")
        for chart, code in result.stale:
            print(f"  {chart}: {code}")

    print(
        f"\n{len(charts)} charts checked: {len(new_errors)} errors, "
        f"{len(new_warnings)} warnings, {len(result.known)} known, {len(result.stale)} stale"
    )

    if new_errors or result.stale:
        return 1
    if args.strict and new_warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Write the `mixes` block into every strategy chart.

    python scripts/derive_mixes.py [charts_dir] [--check]

A chart assigns one action per hand, which states a hard line where real
preflop strategy has a gradient. This marks the hands sitting on such a line so
the trainer accepts either side rather than scoring a legitimate action as a
mistake. The rule is in `logic/mixes.py`; this only applies it and writes the
result.

Run it after `author_chart.py`, which rewrites the actions and would otherwise
drop the block.

`--check` reports what would change without writing, for CI.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from logic.chart_schema import load_charts  # noqa: E402
from logic.mixes import derive_mixes  # noqa: E402
from logic.range_spec import sort_key  # noqa: E402
from logic.strategy import StrategyManager  # noqa: E402


def render_mixes(mixes: dict[str, list[str]]) -> str:
    """One hand per line, in chart order, so a change is a one-line diff."""
    lines = [
        f'    "{hand}": [{", ".join(json.dumps(a) for a in mixes[hand])}]'
        for hand in sorted(mixes, key=sort_key)
    ]
    return '  "mixes": {\n' + ",\n".join(lines) + "\n  }"


def rewrite(path: Path, mixes: dict[str, list[str]]) -> bool:
    """
    Replace or insert the chart's mixes block.

    Edits the text rather than round-tripping through json.dumps, which would
    flatten the hand lists in `actions` and turn every change into a 200-line
    diff.
    """
    original = path.read_text()
    body = original.rstrip()
    assert body.endswith("}"), path

    marker = '\n  "mixes": {'
    if marker in body:
        body = body[: body.index(marker)].rstrip().rstrip(",")
        body = body + "\n}"

    if not mixes:
        updated = body.rstrip() + "\n"
    else:
        inner = body.rstrip()[:-1].rstrip().rstrip(",")
        updated = inner + ",\n" + render_mixes(mixes) + "\n}\n"

    if updated == original:
        return False
    path.write_text(updated)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", default="strategy_charts")
    parser.add_argument("--check", action="store_true", help="report changes without writing")
    args = parser.parse_args()

    charts, _ = load_charts(args.directory)
    # The sampler knows which hands can actually reach each node; a hand hero
    # could never hold there is not a close decision, it is noise.
    sampler = StrategyManager(args.directory).sampler

    changed = []
    for chart_key, data in sorted(charts.items()):
        by_hand = {
            hand: action
            for action, hands in data["actions"].items()
            for hand in hands
        }
        pool = sampler.pool(chart_key)
        mixes = derive_mixes(by_hand, set(pool) if pool else None)
        path = Path(args.directory) / f"{chart_key}.json"

        if args.check:
            if (data.get("mixes") or {}) != mixes:
                changed.append(chart_key)
        elif rewrite(path, mixes):
            changed.append(chart_key)
        print(f"  {chart_key[16:]:30} {len(mixes):3} close decisions")

    if args.check:
        if changed:
            print(f"\n{len(changed)} chart(s) out of date; run scripts/derive_mixes.py")
            return 1
        print("\nall charts up to date")
        return 0

    print(f"\n{len(changed)} chart(s) updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())

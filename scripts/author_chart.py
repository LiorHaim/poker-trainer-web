#!/usr/bin/env python3
"""
Render strategy charts from range specs.

    python scripts/author_chart.py chart_sources/cash_6max_100bb.json

Charts are stored as explicit 169-hand lists because that is what the engine
reads and what makes a diff reviewable, but they are *authored* as range specs
so a range can be read and changed as one line. The spec is copied into each
chart's `metadata.source.spec`, so the generated file carries its own
derivation.

Whatever is not named by a spec becomes FOLD, which is why a generated chart
always covers all 169 hands exactly once.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from logic.chart_schema import ALL_HANDS, ERROR, validate_chart  # noqa: E402
from logic.range_spec import parse_range, render_action_list  # noqa: E402

ACTION_ORDER = ("RAISE", "CALL", "FOLD")


def build_chart(spec: dict, defaults: dict) -> tuple[str, str]:
    """Return (chart_id, file text) for one chart spec."""
    chart_id = spec["chart_id"]
    ranges = {action: parse_range(text) for action, text in spec["ranges"].items()}

    # A defending range is authored as "I raise these, and I continue with these
    # overall" - which is how the decision is actually reasoned about - and the
    # calling range is the difference. Writing CALL directly means restating the
    # whole range minus the raises, which is where carve-out mistakes come from.
    if "DEFEND" in ranges:
        if "CALL" in ranges:
            raise SystemExit(f"{chart_id}: give either DEFEND or CALL, not both")
        defend = ranges.pop("DEFEND")
        raising = ranges.get("RAISE", set())
        outside = raising - defend
        if outside:
            raise SystemExit(
                f"{chart_id}: {sorted(outside)} are raised but missing from DEFEND; "
                f"the raising range must be part of the defending range"
            )
        ranges["CALL"] = defend - raising

    overlaps = _overlapping(ranges)
    if overlaps:
        raise SystemExit(f"{chart_id}: {overlaps} appear under more than one action")

    named = set().union(*ranges.values()) if ranges else set()
    ranges["FOLD"] = ALL_HANDS - named

    metadata = {
        "chart_id": chart_id,
        "description": spec["description"],
        **{key: defaults[key] for key in ("game_type", "table_size", "stack_depth")},
        "hero_position": spec["hero_position"],
        "situation": spec["situation"],
    }
    for key in ("villain_position", "opener_position", "caller_position"):
        if key in spec:
            metadata[key] = spec[key]
    if "sizings" in spec:
        metadata["sizings"] = spec["sizings"]
    metadata["source"] = {**defaults.get("source", {}), **spec.get("source", {}), "spec": spec["ranges"]}
    metadata["explanations"] = spec["explanations"]

    document = {"metadata": metadata, "actions": {}}
    for action in ACTION_ORDER:
        if ranges.get(action):
            document["actions"][action] = sorted(ranges[action])

    found = [i for i in validate_chart(chart_id, document) if i.severity == ERROR]
    if found:
        raise SystemExit(f"{chart_id} failed validation:\n" + "\n".join(f"  {i}" for i in found))

    return chart_id, _render(document, ranges)


def _overlapping(ranges: dict[str, set[str]]) -> list[str]:
    seen: dict[str, int] = {}
    for hands in ranges.values():
        for hand in hands:
            seen[hand] = seen.get(hand, 0) + 1
    return sorted(hand for hand, count in seen.items() if count > 1)


def _render(document: dict, ranges: dict[str, set[str]]) -> str:
    """
    Serialise with the hand lists grouped one rank family per line.

    json.dumps would put every hand on its own line and turn a one-hand change
    into a 200-line diff, so the actions block is rendered by hand.
    """
    metadata = json.dumps({"metadata": document["metadata"]}, indent=2)[1:-2].strip("\n").rstrip()
    lines = ["{", metadata + ",", '  "actions": {']

    present = [action for action in ACTION_ORDER if action in document["actions"]]
    for index, action in enumerate(present):
        body = render_action_list(ranges[action])
        comma = "" if index == len(present) - 1 else ","
        lines.append(f'    "{action}": [')
        lines.append(body)
        lines.append(f"    ]{comma}")

    lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="JSON file of chart specs")
    parser.add_argument("--out", default="strategy_charts")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with open(args.source) as handle:
        document = json.load(handle)

    out_dir = Path(args.out)
    for spec in document["charts"]:
        chart_id, text = build_chart(spec, document.get("defaults", {}))
        target = out_dir / f"{chart_id}.json"
        if args.dry_run:
            print(f"--- {target} ---")
            print(text)
        else:
            target.write_text(text)
            print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

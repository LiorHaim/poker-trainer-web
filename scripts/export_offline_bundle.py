#!/usr/bin/env python3
"""
Write the chart bundle the offline app runs on. Run by `make export-offline`.

    python scripts/export_offline_bundle.py --out ../poker-trainer-offline/data/bundle.json

Charts are loaded in strict mode: a chart that fails validation would otherwise
end up on the phone, where nothing reports it.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from logic.offline_bundle import build_bundle  # noqa: E402
from logic.strategy import StrategyManager  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--out", required=True, type=Path, help="where to write bundle.json")
    parser.add_argument("--charts", default=ROOT / "strategy_charts", type=Path)
    args = parser.parse_args()

    bundle = build_bundle(StrategyManager(args.charts, strict=True))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(bundle, separators=(",", ":"), sort_keys=True))
    print(f"Wrote {len(bundle['charts'])} charts (version {bundle['version']}) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

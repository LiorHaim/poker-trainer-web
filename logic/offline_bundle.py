"""
Everything the offline app needs to run a drill, worked out ahead of time.

The offline trainer (LiorHaim/poker-trainer-offline) runs on a phone with no
server. Rather than port the poker logic to JavaScript and keep two copies in
step, this resolves every part of it that depends only on the charts - what
each node looks like, which hands hero can hold there, which hands count either
way - and writes the result out as data. The phone is left with a weighted
draw, a table lookup, and the review schedule.

Nothing in here depends on the hand dealt: a node's pot, actions and labels
come from the chart's metadata alone, which is what makes precomputing it
possible.
"""
from __future__ import annotations

import hashlib
import json

from . import review
from .chart_schema import POSITIONS
from .nodes import build_scenario
from .scenario import Hand
from .serialize import serialize_node
from .statistics_db import CORRECT_REWARD, INCORRECT_PENALTY, STARTING_BANKROLL
from .strategy import NO_EXPLANATION

#: Bumped when the bundle's shape changes, so the app can refuse one it cannot read.
FORMAT = 1

#: Metadata fields the app filters and labels by. The rest stays server-side.
META_FIELDS = ("game_type", "table_size", "stack_depth", "hero_position", "situation", "description")

#: Any concrete hand will do: the node does not depend on it.
_PLACEHOLDER_HAND = Hand.from_str("AsKs")


def compact_matrix(compiled: dict) -> dict:
    """
    Hand -> action, or hand -> [action, alternative] for a close decision.

    Explanations are per action, not per hand, so they ship once per chart
    beside the matrix instead of 169 times inside it. The app resolves them the
    way `StrategyManager._compile_chart` does.
    """
    matrix = {}
    for hand, data in compiled.items():
        acceptable = [a.value for a in data["acceptable"]]
        matrix[hand] = acceptable if len(acceptable) > 1 else data["action"].value
    return matrix


def build_bundle(strategy_mgr) -> dict:
    charts = {}
    for key in sorted(strategy_mgr.chart_metadata):
        meta = strategy_mgr.chart_metadata[key]
        scenario = build_scenario(meta, _PLACEHOLDER_HAND, key)
        pool = strategy_mgr.sampler.weighted_pool(key)
        charts[key] = {
            "meta": {field: meta[field] for field in META_FIELDS if field in meta},
            "node": serialize_node(scenario),
            "matrix": compact_matrix(strategy_mgr.get_compiled_chart(key)),
            "explanations": dict(meta.get("explanations") or {}),
            "pool": list(pool) if pool else None,
        }

    return {
        "format": FORMAT,
        "version": hashlib.sha256(json.dumps(charts, sort_keys=True).encode()).hexdigest()[:12],
        "charts": charts,
        "no_explanation": NO_EXPLANATION,
        "options": {
            "stack_depths": sorted({int(c["meta"]["stack_depth"]) for c in charts.values()}),
            "situations": sorted({c["meta"]["situation"] for c in charts.values()}),
            "positions": list(POSITIONS),
        },
        "review": {
            "intervals": list(review.INTERVALS),
            "lapse_step_back": review.LAPSE_STEP_BACK,
            "review_share": review.REVIEW_SHARE,
        },
        "bankroll": {
            "starting": STARTING_BANKROLL,
            "correct_reward": CORRECT_REWARD,
            "incorrect_penalty": INCORRECT_PENALTY,
        },
    }

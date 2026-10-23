"""
The offline bundle has to tell the phone exactly what the server would.

The offline app does no poker reasoning of its own, so any drift between this
bundle and the live API is a wrong answer taught with no server to catch it.
"""
import json

import pytest

from logic.nodes import build_scenario
from logic.offline_bundle import build_bundle
from logic.scenario import Action, Hand
from logic.serialize import serialize_scenario
from logic.strategy import StrategyManager


@pytest.fixture(scope="module")
def mgr():
    return StrategyManager("strategy_charts")


@pytest.fixture(scope="module")
def bundle(mgr):
    return build_bundle(mgr)


def test_bundle_is_plain_json(bundle):
    assert json.loads(json.dumps(bundle)) == bundle


def test_every_chart_is_exported(mgr, bundle):
    assert set(bundle["charts"]) == set(mgr.chart_metadata)


def test_every_matrix_covers_all_169_hands(bundle):
    for key, chart in bundle["charts"].items():
        assert len(chart["matrix"]) == 169, key


def test_pool_matches_the_sampler(mgr, bundle):
    for key, chart in bundle["charts"].items():
        expected = mgr.sampler.pool(key)
        if expected is None:
            assert chart["pool"] is None, key
        else:
            hands, weights = chart["pool"]
            assert hands == expected, key
            assert len(weights) == len(hands) and all(w > 0 for w in weights), key


def test_node_matches_a_served_scenario(mgr, bundle):
    hand = Hand.from_str("7h2c")
    for key, chart in bundle["charts"].items():
        served = serialize_scenario(build_scenario(mgr.chart_metadata[key], hand, key))
        served.pop("card1")
        served.pop("card2")
        assert chart["node"] == served, key


def resolve(bundle, chart, hand):
    """The lookup the offline engine does, written out the same way."""
    entry = chart["matrix"][hand]
    acceptable = entry if isinstance(entry, list) else [entry]
    explanations = chart["explanations"]
    return {
        "action": acceptable[0],
        "acceptable": acceptable,
        "explanation": explanations.get(acceptable[0], bundle["no_explanation"]),
        "alternative_explanation": explanations.get(acceptable[1]) if len(acceptable) > 1 else None,
    }


def test_lookup_matches_the_compiled_chart(mgr, bundle):
    for key, chart in bundle["charts"].items():
        for hand, data in mgr.get_compiled_chart(key).items():
            assert resolve(bundle, chart, hand) == {
                "action": data["action"].value,
                "acceptable": [a.value for a in data["acceptable"]],
                "explanation": data["explanation"],
                "alternative_explanation": data["alternative_explanation"],
            }, (key, hand)


def test_version_changes_with_chart_content(mgr, bundle):
    key = next(iter(mgr.charts))
    entry = mgr.charts[key]["AA"]
    original = entry["acceptable"]
    try:
        other = Action.FOLD if entry["action"] != Action.FOLD else Action.CALL
        entry["acceptable"] = [entry["action"], other]
        assert build_bundle(mgr)["version"] != bundle["version"]
    finally:
        entry["acceptable"] = original

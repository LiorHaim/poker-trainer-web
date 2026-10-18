"""
Tests for reachability-conditioned dealing.

The property that matters: at a node hero only reaches by raising, every hand
dealt must be a hand hero would have raised. Hands used to be drawn from the
whole deck, so most deals at those nodes were spots that cannot occur - and
since the chart folds everything outside the reachable range, the answer was
always FOLD.
"""
import random
from collections import Counter
from pathlib import Path

import pytest

from logic.chart_schema import ALL_HANDS, combo_count, load_charts, raising_hands
from logic.sampling import ReachabilitySampler
from logic.scenario import Hand, random_hand_of

CHART_DIR = Path(__file__).resolve().parent.parent / "strategy_charts"


@pytest.fixture(scope="module")
def charts():
    return load_charts(CHART_DIR)[0]


@pytest.fixture(scope="module")
def sampler(charts):
    return ReachabilitySampler(charts)


# --- Dealing a specific hand class ------------------------------------------

@pytest.mark.parametrize("notation", sorted(ALL_HANDS))
def test_dealt_hand_matches_its_class(notation):
    assert random_hand_of(notation).range_notation == notation


def test_pairs_get_two_different_suits():
    for _ in range(50):
        hand = random_hand_of("AA")
        assert hand.card1.suit != hand.card2.suit


def test_suited_hands_share_a_suit():
    for _ in range(50):
        hand = random_hand_of("AKs")
        assert hand.card1.suit == hand.card2.suit


def test_offsuit_hands_do_not():
    for _ in range(50):
        hand = random_hand_of("AKo")
        assert hand.card1.suit != hand.card2.suit


def test_all_combinations_are_reachable():
    """A suited hand has 4 combinations and all should come up."""
    seen = {(h.card1.suit, h.card2.suit) for h in (random_hand_of("AKs") for _ in range(200))}
    assert len(seen) == 4


def test_bad_notation_is_rejected():
    with pytest.raises(ValueError):
        random_hand_of("AK")


# --- Reachability -----------------------------------------------------------

def test_nodes_hero_has_not_acted_at_deal_from_the_whole_deck(sampler, charts):
    for key, data in charts.items():
        if data["metadata"]["situation"] in ("RFI", "vs_RFI", "squeeze"):
            assert sampler.pool(key) is None, key


def test_deeper_nodes_deal_only_from_the_prior_range(sampler, charts):
    """
    The core property. Previously ~75% of these deals were impossible spots.

    Each node has its own prior range: hero opened to reach a vs_3Bet node,
    3-bet to reach vs_4Bet, and opened then 4-bet to reach vs_5Bet.
    """
    by_situation = {
        "vs_3Bet": lambda m: ("RFI", m["hero_position"], None),
        "vs_4Bet": lambda m: ("vs_RFI", m["hero_position"], m["villain_position"]),
        "vs_5Bet": lambda m: ("vs_3Bet", m["hero_position"], m["villain_position"]),
    }
    raises = {
        (d["metadata"]["situation"], d["metadata"]["hero_position"],
         d["metadata"].get("villain_position") if d["metadata"]["situation"] != "RFI" else None):
            raising_hands(d)
        for d in charts.values()
    }

    checked = 0
    for key, data in charts.items():
        meta = data["metadata"]
        lookup = by_situation.get(meta["situation"])
        if lookup is None:
            continue
        expected = raises.get(lookup(meta))
        if expected is None:
            # No chart defines that range; the sampler falls back to a looser
            # one, which the validator reports as imprecise-prior-range.
            continue

        assert set(sampler.pool(key)) == expected, key
        for _ in range(100):
            assert sampler.deal(key).range_notation in expected, key
        checked += 1

    reached_by_raising = sum(
        1 for d in charts.values() if d["metadata"]["situation"] in by_situation
    )
    assert checked == reached_by_raising, (
        f"{reached_by_raising - checked} node(s) hero reaches by raising have no chart "
        f"defining that range, so they deal from a looser one"
    )
    assert checked > 0


def test_no_dealt_hand_is_an_automatic_fold(sampler, charts):
    """
    At these nodes every hand outside hero's prior range is a fold in the chart.
    Dealing only reachable hands means the drill stops handing out free folds.
    """
    from logic.strategy import StrategyManager

    manager = StrategyManager(CHART_DIR)
    for key in charts:
        if sampler.pool(key) is None:
            continue
        compiled = manager.get_compiled_chart(key)
        non_fold = sum(
            1 for _ in range(200)
            if compiled[sampler.deal(key).range_notation]["action"].value != "FOLD"
        )
        assert non_fold > 0, f"{key} deals nothing but folds"


# --- Weighting --------------------------------------------------------------

def test_deals_are_weighted_by_combinations():
    """
    An offsuit hand is 12 combinations and a suited one 4, so a range of one
    each should deal the offsuit hand about three times as often. Dealing hand
    classes uniformly would distort which spots the user sees.
    """
    charts = {
        "rfi": {
            "metadata": {"game_type": "cash", "table_size": 6, "stack_depth": 100,
                         "hero_position": "BTN", "situation": "RFI"},
            "actions": {"RAISE": ["AKs", "AKo"], "FOLD": sorted(ALL_HANDS - {"AKs", "AKo"})},
        },
        "vs3bet": {
            "metadata": {"game_type": "cash", "table_size": 6, "stack_depth": 100,
                         "hero_position": "BTN", "situation": "vs_3Bet", "villain_position": "BB"},
            "actions": {"CALL": ["AKs", "AKo"], "FOLD": sorted(ALL_HANDS - {"AKs", "AKo"})},
        },
    }
    random.seed(7)
    sampler = ReachabilitySampler(charts)
    counts = Counter(sampler.deal("vs3bet").range_notation for _ in range(4000))
    ratio = counts["AKo"] / counts["AKs"]
    assert 2.4 < ratio < 3.6, counts
    assert combo_count("AKo") / combo_count("AKs") == 3


def test_missing_prior_range_falls_back_to_the_deck(caplog):
    """A node with no chart describing how hero got there must still be playable."""
    charts = {
        "orphan": {
            "metadata": {"game_type": "cash", "table_size": 6, "stack_depth": 100,
                         "hero_position": "BTN", "situation": "vs_3Bet", "villain_position": "BB"},
            "actions": {"FOLD": sorted(ALL_HANDS)},
        }
    }
    sampler = ReachabilitySampler(charts)
    assert sampler.pool("orphan") is None
    assert isinstance(sampler.deal("orphan"), Hand)


def test_unknown_chart_key_falls_back_to_the_deck(sampler):
    assert isinstance(sampler.deal("no_such_chart"), Hand)

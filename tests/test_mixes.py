"""
Tests for close decisions.

A chart assigns one action per hand, which states a hard line where real
preflop strategy has a gradient. Roughly a quarter of reachable deals sit on
such a line. Scoring those as a single right answer marked a legitimate action
wrong and docked the user for it, which over a session trains the mixed action
out of them.

The derivation is structural, not solved: it finds which hands are *close*, not
how often to take each line. These tests pin the guards that keep it from
saying something false.
"""
import json
from pathlib import Path

import pytest

from logic.chart_schema import ALL_HANDS, ERROR, validate_chart
from logic.mixes import MIN_GROUP_FOR_MIXING, derive_mixes, neighbours
from logic.strategy import StrategyManager

CHART_DIR = Path(__file__).resolve().parent.parent / "strategy_charts"


# --- Matrix adjacency -------------------------------------------------------

def test_pairs_neighbour_the_pairs_either_side():
    assert set(neighbours("TT")) == {"JJ", "99"}


def test_the_best_and_worst_pair_have_one_neighbour():
    assert neighbours("AA") == ["KK"]
    assert neighbours("22") == ["33"]


def test_suited_hands_neighbour_the_next_kicker():
    assert set(neighbours("A5s")) == {"A6s", "A4s"}
    assert set(neighbours("KQs")) == {"KJs"}  # nothing above Q under a king


def test_suited_and_offsuit_never_mix():
    assert all(n.endswith("s") for n in neighbours("A5s"))
    assert all(n.endswith("o") for n in neighbours("A5o"))


# --- Derivation -------------------------------------------------------------

def a_range(raise_hands, call_hands=()):
    actions = {}
    for hand in ALL_HANDS:
        actions[hand] = (
            "RAISE" if hand in raise_hands else "CALL" if hand in call_hands else "FOLD"
        )
    return actions


def test_a_hand_beside_a_different_action_is_close():
    mixes = derive_mixes(a_range({"AA", "KK", "QQ", "JJ", "TT"}))
    assert mixes["TT"] == ["RAISE", "FOLD"]   # weakest raise
    assert mixes["99"] == ["FOLD", "RAISE"]   # strongest fold


def test_a_hand_surrounded_by_its_own_action_is_pure():
    mixes = derive_mixes(a_range({"AA", "KK", "QQ", "JJ", "TT"}))
    assert "AA" not in mixes
    assert "KK" not in mixes
    assert "22" not in mixes


def test_no_hand_is_allowed_every_action():
    """Accepting all three leaves no wrong answer, which teaches nothing."""
    actions = a_range({"A6s"}, call_hands={"A5s"})  # A5s sits between a raise and a fold
    mixes = derive_mixes(actions)
    assert all(len(v) <= 2 for v in mixes.values())
    assert "A5s" not in mixes, "a hand pulled two ways is ambiguous, so the chart stands"


def test_tiny_action_groups_are_left_pure():
    """
    With a raising range of {AA, KK}, KK touches a calling hand and would be
    marked callable - but calling KK facing a jam is a mistake, not a close
    decision. Every member of a two-hand group is an edge by construction.
    """
    actions = a_range({"AA", "KK"}, call_hands={"QQ", "JJ", "TT"})
    mixes = derive_mixes(actions)
    assert "KK" not in mixes
    assert "AA" not in mixes
    assert MIN_GROUP_FOR_MIXING == 3


def test_unreachable_hands_are_not_marked():
    """Hero cannot hold 72o facing a 5-bet, so it is not a close decision there."""
    actions = a_range({"AA", "KK", "QQ"}, call_hands={"JJ", "TT", "99"})
    reachable = {"AA", "KK", "QQ", "JJ", "TT", "99"}
    assert set(derive_mixes(actions, reachable)) <= reachable


def test_the_primary_action_always_comes_first():
    for hand, allowed in derive_mixes(a_range({"AA", "KK", "QQ", "JJ"})).items():
        assert allowed[0] == a_range({"AA", "KK", "QQ", "JJ"})[hand]


# --- The shipped charts -----------------------------------------------------

@pytest.fixture(scope="module")
def manager():
    return StrategyManager(CHART_DIR)


def test_every_chart_has_a_mixes_block_that_validates():
    for path in CHART_DIR.glob("*.json"):
        data = json.loads(path.read_text())
        found = [i for i in validate_chart(path.stem, data) if i.severity == ERROR]
        assert not found, "\n".join(str(i) for i in found)


def test_premium_hands_are_never_a_close_decision(manager):
    """No chart may tell the user that folding aces is also fine."""
    for key in manager.charts:
        entry = manager.get_compiled_chart(key)["AA"]
        assert len(entry["acceptable"]) == 1, f"{key} treats AA as a close decision"


def test_mixes_are_up_to_date_with_the_actions():
    """
    Guards the ordering trap: author_chart.py rewrites actions and would leave
    a stale mixes block behind. Run scripts/derive_mixes.py after it.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "scripts/derive_mixes.py", str(CHART_DIR), "--check"],
        capture_output=True, text=True,
        cwd=str(CHART_DIR.parent),
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_compiled_charts_expose_acceptable_actions(manager):
    chart = manager.get_compiled_chart("cash_6max_100bb_UTG_RFI")
    assert [a.value for a in chart["AA"]["acceptable"]] == ["RAISE"]
    assert [a.value for a in chart["76s"]["acceptable"]] == ["RAISE", "FOLD"]
    assert [a.value for a in chart["72o"]["acceptable"]] == ["FOLD"]

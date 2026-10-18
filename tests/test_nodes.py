"""
Tests for preflop node definitions.

The pot and to-call figures are what the user sees and reasons about, and they
used to come from a table of hardcoded numbers that did not match the sizes the
charts were built for. Each case below works the money out by hand.
"""
import pytest

from logic.nodes import DEFAULT_SIZINGS, UnknownSituation, build_node, build_scenario, sizings_for
from logic.scenario import Action, Hand, Position

SIZES = {"open_bb": 2.5, "3bet_bb": 11.0, "4bet_bb": 24.0, "5bet_bb": 100.0}


def meta(**overrides):
    base = {"table_size": 6, "stack_depth": 100, "sizings": SIZES}
    base.update(overrides)
    return base


# --- RFI --------------------------------------------------------------------

def test_rfi_pot_is_the_blinds():
    node = build_node(meta(hero_position="BTN", situation="RFI"))
    assert node.pot_bb == 1.5
    assert node.actions_before_hero == []


def test_rfi_call_is_a_limp_for_the_big_blind():
    assert build_node(meta(hero_position="BTN", situation="RFI")).to_call_bb == 1.0


def test_rfi_from_the_small_blind_only_completes():
    """SB already has 0.5 in, so calling costs 0.5, not a full blind."""
    node = build_node(meta(hero_position="SB", situation="RFI"))
    assert node.to_call_bb == 0.5
    assert node.hero_invested_bb == 0.5


# --- Facing an open ---------------------------------------------------------

def test_vs_rfi_from_the_big_blind():
    """Dead SB 0.5 + hero's posted 1.0 + the 2.5 open = 4.0, and 1.5 more to call."""
    node = build_node(meta(hero_position="BB", situation="vs_RFI", villain_position="BTN"))
    assert node.pot_bb == 4.0
    assert node.to_call_bb == 1.5
    assert node.raise_label == "3-Bet"


def test_vs_rfi_from_a_non_blind_seat():
    """Both blinds are dead money: 1.5 + the 2.5 open, and the full 2.5 to call."""
    node = build_node(meta(hero_position="BTN", situation="vs_RFI", villain_position="CO"))
    assert node.pot_bb == 4.0
    assert node.to_call_bb == 2.5


def test_villain_blind_is_not_counted_twice():
    """
    When the opener is the SB, their 0.5 is already inside the open. Counting it
    again as dead money would overstate the pot.
    """
    node = build_node(meta(hero_position="BB", situation="vs_RFI", villain_position="SB"))
    assert node.pot_bb == 1.0 + 2.5  # hero's big blind + the open, nothing dead
    assert node.to_call_bb == 1.5


# --- Deeper nodes -----------------------------------------------------------

def test_vs_3bet_hero_already_has_the_open_in():
    node = build_node(meta(hero_position="UTG", situation="vs_3Bet", villain_position="BTN"))
    assert node.hero_invested_bb == 2.5
    assert node.pot_bb == 1.5 + 2.5 + 11.0
    assert node.to_call_bb == 11.0 - 2.5
    assert node.raise_label == "4-Bet"


def test_vs_4bet_is_hero_3betting_into_a_4bet():
    node = build_node(meta(hero_position="BTN", situation="vs_4Bet", villain_position="MP"))
    assert node.hero_invested_bb == 11.0
    assert node.pot_bb == 1.5 + 11.0 + 24.0
    assert node.to_call_bb == 24.0 - 11.0
    assert "you 3-bet" in node.action_text
    assert node.raise_label == "5-Bet Jam"


def test_vs_5bet_is_hero_4betting_into_a_jam():
    node = build_node(meta(hero_position="UTG", situation="vs_5Bet", villain_position="MP"))
    assert node.hero_invested_bb == 24.0
    assert node.to_call_bb == 100.0 - 24.0
    assert "you 4-bet" in node.action_text


def test_squeeze_counts_both_villains():
    node = build_node(
        meta(hero_position="BB", situation="squeeze", opener_position="CO", caller_position="BTN")
    )
    assert node.pot_bb == 0.5 + 1.0 + 2.5 * 2
    assert node.to_call_bb == 1.5
    assert len(node.actions_before_hero) == 2
    assert node.actions_before_hero[1].action == Action.CALL


# --- Sizings ----------------------------------------------------------------

def test_chart_sizings_are_used():
    node = build_node(
        meta(hero_position="BB", situation="vs_RFI", villain_position="BTN", sizings={"open_bb": 5.0})
    )
    assert node.to_call_bb == 4.0


def test_missing_sizings_fall_back_to_defaults():
    base = {"table_size": 6, "stack_depth": 100, "hero_position": "BB",
            "situation": "vs_RFI", "villain_position": "BTN"}
    assert build_node(base).to_call_bb == DEFAULT_SIZINGS["open_bb"] - 1.0


def test_partial_sizings_are_completed_from_defaults():
    assert sizings_for({"sizings": {"open_bb": 3.0}})["3bet_bb"] == DEFAULT_SIZINGS["3bet_bb"]


def test_unknown_situation_is_an_error():
    with pytest.raises(UnknownSituation):
        build_node(meta(hero_position="BTN", situation="vs_6Bet"))


# --- Scenario ---------------------------------------------------------------

def test_build_scenario_carries_the_node_figures():
    scenario = build_scenario(
        meta(hero_position="BB", situation="vs_RFI", villain_position="BTN"),
        Hand.from_str("AhKs"),
        "some_chart",
    )
    assert scenario.hero_position == Position.BB
    assert scenario.chart_key == "some_chart"
    assert scenario.pot_bb == 4.0
    assert scenario.to_call_bb == 1.5
    assert scenario.hero_hand.range_notation == "AKo"

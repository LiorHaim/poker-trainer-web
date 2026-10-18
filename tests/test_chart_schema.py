"""
Tests for the validator itself.

`tests/test_chart_invariants.py` asserts the shipped charts are clean. That is
only meaningful if the validator actually catches a dirty one, so each check
here feeds it a chart with one specific defect and asserts the right code fires.
"""
import pytest

from logic.chart_schema import (
    ALL_HANDS,
    ERROR,
    ChartIssue,
    apply_baseline,
    decision_node_id,
    is_valid_hand,
    validate_chart,
    validate_chart_set,
)


def codes(issues, severity=None):
    return {i.code for i in issues if severity is None or i.severity == severity}


def good_chart(**metadata_overrides):
    """A minimal chart that passes: everything raises, every hand covered."""
    metadata = {
        "chart_id": "cash_6max_100bb_BTN_RFI",
        "description": "test chart",
        "game_type": "cash",
        "table_size": 6,
        "stack_depth": 100,
        "hero_position": "BTN",
        "situation": "RFI",
        "explanations": {"RAISE": "because"},
        "sizings": {"open_bb": 2.5},
    }
    metadata.update(metadata_overrides)
    return {"metadata": metadata, "actions": {"RAISE": sorted(ALL_HANDS)}}


# --- Hand notation ----------------------------------------------------------

@pytest.mark.parametrize("hand", ["AA", "22", "AKs", "AKo", "72o", "32s"])
def test_valid_hands(hand):
    assert is_valid_hand(hand)


@pytest.mark.parametrize("hand", ["KAs", "AAs", "AAo", "AK", "AKx", "", "akS", None, 7])
def test_invalid_hands(hand):
    assert not is_valid_hand(hand)


def test_there_are_exactly_169_hands():
    assert len(ALL_HANDS) == 169


# --- Per-chart checks -------------------------------------------------------

def test_good_chart_has_no_errors():
    assert not codes(validate_chart("cash_6max_100bb_BTN_RFI", good_chart()), ERROR)


def test_detects_duplicate_hand():
    chart = good_chart()
    chart["actions"]["FOLD"] = ["72o"]  # already in RAISE
    chart["metadata"]["explanations"]["FOLD"] = "because"
    assert "duplicate-hand" in codes(validate_chart("cash_6max_100bb_BTN_RFI", chart), ERROR)


def test_detects_incomplete_coverage():
    chart = good_chart()
    chart["actions"]["RAISE"].remove("72o")
    assert "incomplete-coverage" in codes(validate_chart("cash_6max_100bb_BTN_RFI", chart), ERROR)


def test_detects_hand_repeated_within_one_action():
    chart = good_chart()
    chart["actions"]["RAISE"].append("AA")
    found = codes(validate_chart("cash_6max_100bb_BTN_RFI", chart), ERROR)
    assert "repeated-hand" in found


def test_detects_bad_hand_notation():
    chart = good_chart()
    chart["actions"]["RAISE"].append("KAs")
    assert "bad-hand" in codes(validate_chart("cash_6max_100bb_BTN_RFI", chart), ERROR)


def test_detects_chart_id_mismatch():
    assert "chart-id-mismatch" in codes(validate_chart("some_other_name", good_chart()), ERROR)


def test_detects_missing_metadata_key():
    chart = good_chart()
    del chart["metadata"]["description"]
    assert "missing-metadata-key" in codes(validate_chart("cash_6max_100bb_BTN_RFI", chart), ERROR)


def test_detects_missing_villain_for_situation():
    chart = good_chart(situation="vs_RFI")
    found = validate_chart("cash_6max_100bb_BTN_RFI", chart)
    assert "missing-metadata-key" in codes(found, ERROR)


def test_detects_villain_in_hero_seat():
    chart = good_chart(situation="vs_RFI", villain_position="BTN")
    assert "self-villain" in codes(validate_chart("cash_6max_100bb_BTN_RFI", chart), ERROR)


def test_detects_unknown_action():
    chart = good_chart()
    chart["actions"]["LIMP"] = []
    assert "bad-action" in codes(validate_chart("cash_6max_100bb_BTN_RFI", chart), ERROR)


def test_detects_missing_explanation():
    chart = good_chart()
    chart["metadata"]["explanations"] = {}
    assert "missing-explanation" in codes(validate_chart("cash_6max_100bb_BTN_RFI", chart), ERROR)


def test_detects_bad_position():
    chart = good_chart(hero_position="LOJ")
    assert "bad-position" in codes(validate_chart("cash_6max_100bb_BTN_RFI", chart), ERROR)


def test_detects_bad_situation():
    chart = good_chart(situation="vs_6Bet")
    assert "bad-situation" in codes(validate_chart("cash_6max_100bb_BTN_RFI", chart), ERROR)


def test_detects_non_integer_stack_depth():
    chart = good_chart(stack_depth="100")
    assert "bad-metadata-type" in codes(validate_chart("cash_6max_100bb_BTN_RFI", chart), ERROR)


def test_rejects_missing_sizings():
    """
    Without sizings the engine falls back to defaults, and the pot odds shown
    do not match the sizes the ranges were built for.
    """
    chart = good_chart()
    del chart["metadata"]["sizings"]
    assert "missing-sizings" in codes(validate_chart("cash_6max_100bb_BTN_RFI", chart), ERROR)


def test_rejects_negative_sizing():
    chart = good_chart(sizings={"open_bb": -1})
    assert "bad-sizing-value" in codes(validate_chart("cash_6max_100bb_BTN_RFI", chart), ERROR)


def test_rejects_non_object_chart():
    assert "not-an-object" in codes(validate_chart("x", ["nope"]), ERROR)


# --- Cross-chart checks -----------------------------------------------------

def test_three_bet_is_no_longer_a_separate_situation():
    """
    `3Bet` described the same decision as `vs_RFI` and shipped as a second chart
    per spot with conflicting answers. Phase 1 removed it; a chart that still
    uses it must be rejected rather than quietly loaded.
    """
    from logic.chart_schema import SITUATIONS

    assert "3Bet" not in SITUATIONS
    assert "bad-situation" in codes(
        validate_chart("cash_6max_100bb_BTN_RFI", good_chart(situation="3Bet")), ERROR
    )


def test_different_villains_are_different_nodes():
    base = {"game_type": "cash", "table_size": 6, "stack_depth": 100,
            "hero_position": "BB", "situation": "vs_RFI"}
    assert decision_node_id({**base, "villain_position": "BTN"}) != decision_node_id(
        {**base, "villain_position": "CO"}
    )


def test_detects_duplicate_node():
    charts = {
        "a": good_chart(chart_id="a", situation="vs_RFI", villain_position="CO"),
        "b": good_chart(chart_id="b", situation="vs_RFI", villain_position="CO"),
    }
    assert "duplicate-node" in codes(validate_chart_set(charts), ERROR)


def test_detects_unreachable_continue():
    rfi = good_chart()
    rfi["actions"] = {"RAISE": ["AA", "KK"], "FOLD": sorted(ALL_HANDS - {"AA", "KK"})}
    rfi["metadata"]["explanations"]["FOLD"] = "because"

    vs_3bet = good_chart(chart_id="vs3bet", situation="vs_3Bet", villain_position="BB")
    vs_3bet["actions"] = {"CALL": ["72o"], "FOLD": sorted(ALL_HANDS - {"72o"})}
    vs_3bet["metadata"]["explanations"] = {"CALL": "because", "FOLD": "because"}

    found = validate_chart_set({"cash_6max_100bb_BTN_RFI": rfi, "vs3bet": vs_3bet})
    assert "unreachable-continue" in codes(found, ERROR)


# --- Baseline ---------------------------------------------------------------

def test_baseline_suppresses_known_and_surfaces_new():
    known = ChartIssue("chart_a", "duplicate-node", ERROR, "known")
    novel = ChartIssue("chart_b", "duplicate-hand", ERROR, "new")
    result = apply_baseline([known, novel], {("chart_a", "duplicate-node")})
    assert result.known == [known]
    assert result.new == [novel]
    assert result.stale == []


def test_baseline_reports_stale_entries():
    result = apply_baseline([], {("chart_a", "duplicate-node")})
    assert result.stale == [("chart_a", "duplicate-node")]

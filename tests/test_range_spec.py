"""
Tests for range notation parsing.

Charts are authored from these specs, so a parser bug writes a wrong range into
a chart. The `+` suffix in particular is ambiguous and follows the usual
convention: same high card walks the kicker up (`ATs+`), a one-gap connector
walks the whole hand up (`54s+`).
"""
import pytest

from logic.chart_schema import ALL_HANDS
from logic.range_spec import (
    RangeSpecError,
    group_by_row,
    parse_range,
    parse_term,
    render_action_list,
)


def test_single_hands():
    assert parse_term("AA") == {"AA"}
    assert parse_term("AKs") == {"AKs"}
    assert parse_term("72o") == {"72o"}


def test_reversed_ranks_are_normalised():
    assert parse_term("KAs") == {"AKs"}
    assert parse_term("27o") == {"72o"}


def test_case_insensitive():
    assert parse_term("aks") == {"AKs"}
    assert parse_term("AKO") == {"AKo"}


def test_pairs_upward():
    assert parse_term("TT+") == {"TT", "JJ", "QQ", "KK", "AA"}
    assert len(parse_term("22+")) == 13


def test_pair_range():
    assert parse_term("99-66") == {"99", "88", "77", "66"}
    assert parse_term("66-99") == {"99", "88", "77", "66"}


def test_kicker_upward():
    assert parse_term("ATs+") == {"ATs", "AJs", "AQs", "AKs"}
    assert parse_term("KTs+") == {"KTs", "KJs", "KQs"}
    assert parse_term("AJo+") == {"AJo", "AQo", "AKo"}


def test_kicker_range():
    assert parse_term("A5s-A2s") == {"A5s", "A4s", "A3s", "A2s"}
    assert parse_term("A2s-A5s") == {"A5s", "A4s", "A3s", "A2s"}


def test_connectors_walk_upward():
    """A one-gap hand with '+' keeps the gap and raises the top card."""
    assert parse_term("54s+") == {
        "54s", "65s", "76s", "87s", "98s", "T9s", "JTs", "QJs", "KQs", "AKs",
    }
    assert parse_term("QJs+") == {"QJs", "KQs", "AKs"}


def test_whole_range():
    hands = parse_range("22+, ATs+, A5s-A2s, KQo")
    assert "22" in hands and "AA" in hands
    assert "AKs" in hands and "A3s" in hands and "KQo" in hands
    assert "A9s" not in hands


def test_separators_are_flexible():
    assert parse_range("AA KK") == parse_range("AA,KK") == parse_range("AA, KK") == {"AA", "KK"}


def test_overlapping_terms_are_idempotent():
    assert parse_range("ATs+, AKs, AQs") == parse_range("ATs+")


def test_every_parsed_hand_is_canonical():
    hands = parse_range("22+, A2s+, K2s+, Q2s+, J2s+, T2s+, 92s+, 82s+, 72s+, 62s+, 52s+, 42s+, 32s, "
                        "A2o+, K2o+, Q2o+, J2o+, T2o+, 92o+, 82o+, 72o+, 62o+, 52o+, 42o+, 32o")
    assert hands <= ALL_HANDS


@pytest.mark.parametrize("bad", ["", "XX", "AAs", "AA+s", "AKs-KQs", "AKs-AQo", "A", "AKsx"])
def test_invalid_terms_raise(bad):
    if bad == "":
        assert parse_term(bad) == set()
        return
    with pytest.raises(RangeSpecError):
        parse_term(bad)


# --- Formatting -------------------------------------------------------------

def test_rows_group_by_family():
    rows = group_by_row(parse_range("AA, KK, AKs, AQs, KQs, AKo"))
    assert rows[0] == ["AA", "KK"]
    assert rows[1] == ["AKs", "AQs"]
    assert rows[2] == ["KQs"]
    assert rows[3] == ["AKo"]


def test_render_is_valid_json_array_body():
    import json

    body = render_action_list(parse_range("22+, AKs, AKo"))
    assert json.loads(f"[{body}]")


def test_render_keeps_one_family_per_line():
    body = render_action_list(parse_range("AKs, AQs, KQs"))
    assert body.count("\n") == 1  # two lines: the A row and the K row

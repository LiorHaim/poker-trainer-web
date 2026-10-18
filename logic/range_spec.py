"""
Poker range notation: "22+, ATs+, A5s-A2s, KQo" -> a set of hands.

Charts are stored as explicit 169-hand lists because that is what the engine
needs and what makes a diff reviewable. Writing those lists by hand is how the
duplicate and missing-hand bugs got in, so charts are authored as range specs
and expanded here.

The spec is recorded in each chart's `metadata.source.spec`, so a 60-hand range
can be read, reviewed and changed as one line instead of eleven.

Supported terms:

    AA              a single hand
    AKs AKo         suited / offsuit
    22+             pairs upward: 22, 33, ... AA
    TT+             TT, JJ, QQ, KK, AA
    ATs+            same high card, kicker upward: ATs, AJs, AQs, AKs
    A5s-A2s         explicit kicker range, either direction
    99-66           explicit pair range, either direction
    AKo+            offsuit, kicker upward
    54s+            connectors keeping the gap: 54s, 65s, 76s ... KQs

Terms are separated by commas or whitespace. Case-insensitive.
"""
from __future__ import annotations

import re

RANKS = "AKQJT98765432"
RANK_VALUE = {rank: len(RANKS) - index for index, rank in enumerate(RANKS)}


class RangeSpecError(ValueError):
    """Raised when a range spec cannot be parsed."""


def _hand(high: str, low: str, suffix: str) -> str:
    """Normalise a pair of ranks into canonical notation."""
    if RANK_VALUE[high] < RANK_VALUE[low]:
        high, low = low, high
    if high == low:
        return high + low
    return f"{high}{low}{suffix}"


def _pairs_from(rank: str) -> set[str]:
    return {r + r for r in RANKS if RANK_VALUE[r] >= RANK_VALUE[rank]}


def _pair_range(first: str, second: str) -> set[str]:
    low, high = sorted((RANK_VALUE[first], RANK_VALUE[second]))
    return {r + r for r in RANKS if low <= RANK_VALUE[r] <= high}


def _kickers_from(high: str, low: str, suffix: str) -> set[str]:
    """ATs+ -> every kicker from T up to one below the high card."""
    return {
        _hand(high, kicker, suffix)
        for kicker in RANKS
        if RANK_VALUE[low] <= RANK_VALUE[kicker] < RANK_VALUE[high]
    }


def _kicker_range(high: str, first: str, second: str, suffix: str) -> set[str]:
    low_value, high_value = sorted((RANK_VALUE[first], RANK_VALUE[second]))
    return {
        _hand(high, kicker, suffix)
        for kicker in RANKS
        if low_value <= RANK_VALUE[kicker] <= high_value and kicker != high
    }


def _connectors_from(high: str, low: str, suffix: str) -> set[str]:
    """54s+ -> every hand with the same gap and a higher top card."""
    gap = RANK_VALUE[high] - RANK_VALUE[low]
    hands = set()
    for candidate in RANKS:
        partner_value = RANK_VALUE[candidate] - gap
        if RANK_VALUE[candidate] < RANK_VALUE[high] or partner_value < 1:
            continue
        partner = next(r for r in RANKS if RANK_VALUE[r] == partner_value)
        hands.add(_hand(candidate, partner, suffix))
    return hands


PAIR = re.compile(r"^([2-9TJQKA])\1$")
PAIR_PLUS = re.compile(r"^([2-9TJQKA])\1\+$")
PAIR_RANGE = re.compile(r"^([2-9TJQKA])\1-([2-9TJQKA])\2$")
HAND = re.compile(r"^([2-9TJQKA])([2-9TJQKA])([so])$")
HAND_PLUS = re.compile(r"^([2-9TJQKA])([2-9TJQKA])([so])\+$")
HAND_RANGE = re.compile(r"^([2-9TJQKA])([2-9TJQKA])([so])-([2-9TJQKA])([2-9TJQKA])([so])$")


def parse_term(term: str) -> set[str]:
    """Expand one term of a range spec."""
    term = term.strip().upper().replace("S", "s").replace("O", "o")
    if not term:
        return set()

    if PAIR.match(term):
        return {term}
    if match := PAIR_PLUS.match(term):
        return _pairs_from(match.group(1))
    if match := PAIR_RANGE.match(term):
        return _pair_range(match.group(1), match.group(2))

    if match := HAND.match(term):
        high, low, suffix = match.groups()
        if high == low:
            raise RangeSpecError(f"{term!r}: a pair cannot be suited or offsuit")
        return {_hand(high, low, suffix)}

    if match := HAND_PLUS.match(term):
        high, low, suffix = match.groups()
        if high == low:
            raise RangeSpecError(f"{term!r}: a pair cannot be suited or offsuit")
        if RANK_VALUE[high] < RANK_VALUE[low]:
            high, low = low, high
        # "AJs+" walks the kicker up; "54s+" walks the whole hand up keeping the gap.
        if RANK_VALUE[high] - RANK_VALUE[low] == 1:
            return _connectors_from(high, low, suffix)
        return _kickers_from(high, low, suffix)

    if match := HAND_RANGE.match(term):
        high_a, low_a, suffix_a, high_b, low_b, suffix_b = match.groups()
        if suffix_a != suffix_b:
            raise RangeSpecError(f"{term!r}: both ends must be suited or both offsuit")
        if high_a != high_b:
            raise RangeSpecError(f"{term!r}: both ends must share a high card")
        return _kicker_range(high_a, low_a, low_b, suffix_a)

    raise RangeSpecError(f"{term!r} is not valid range notation")


def parse_range(spec: str) -> set[str]:
    """Expand a full spec. Overlapping terms are fine; the result is a set."""
    hands: set[str] = set()
    for term in re.split(r"[,\s]+", spec.strip()):
        if term:
            hands |= parse_term(term)
    return hands


# --- Output formatting ------------------------------------------------------

def sort_key(hand: str) -> tuple:
    """Pairs first, then suited, then offsuit; strongest first within each."""
    high, low = hand[0], hand[1]
    suffix = hand[2:] or ""
    group = {"": 0, "s": 1, "o": 2}[suffix]
    return (group, -RANK_VALUE[high], -RANK_VALUE[low])


def group_by_row(hands: set[str]) -> list[list[str]]:
    """
    Group hands into the one-rank-family-per-line layout charts use, so a
    one-hand change stays a one-line diff. See docs/CHART_SCHEMA.md.
    """
    rows: dict[tuple, list[str]] = {}
    for hand in sorted(hands, key=sort_key):
        suffix = hand[2:] or ""
        key = ("pair",) if not suffix else (hand[0], suffix)
        rows.setdefault(key, []).append(hand)
    return list(rows.values())


def render_action_list(hands: set[str], indent: int = 6) -> str:
    """Render a hand set as the JSON array body, grouped one family per line."""
    pad = " " * indent
    rows = group_by_row(hands)
    lines = [pad + ", ".join(f'"{hand}"' for hand in row) for row in rows]
    return ",\n".join(lines)

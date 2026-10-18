"""
Preflop node definitions: turning a chart's metadata into a concrete spot.

This is the single place that knows what a situation *means* - who acted, for
how much, what is in the pot, and what hero has to call. It used to be an
if/elif chain duplicated across `app.py`, `logic/trainer.py` and a JavaScript
function in `static/index.html`, with a set of hardcoded pot sizes in
`TrainingScenario` that disagreed with all of them.

Bet sizes come from `metadata.sizings` on the chart, so a chart built for a
2.5bb open is drilled at 2.5bb. Charts without a sizings block fall back to
`DEFAULT_SIZINGS` and are reported by the validator.
"""
from __future__ import annotations

from dataclasses import dataclass

from .scenario import Action, Hand, Position, PreflopAction, TrainingScenario

SMALL_BLIND = 0.5
BIG_BLIND = 1.0

#: Used when a chart does not declare its own sizings. These are only a
#: fallback - a chart whose ranges were built for a different size will show the
#: user pot odds that do not match the range they are being tested on.
DEFAULT_SIZINGS = {
    "open_bb": 2.5,
    "3bet_bb": 11.0,
    "4bet_bb": 24.0,
    "5bet_bb": 100.0,
}


class UnknownSituation(ValueError):
    """Raised for a situation with no node definition."""


@dataclass(frozen=True)
class Node:
    """A resolved spot: who did what, and the money already in."""

    situation: str
    hero_position: Position
    actions_before_hero: list[PreflopAction]
    hero_invested_bb: float
    pot_bb: float
    to_call_bb: float
    raise_label: str
    action_text: str


def blind_posted(position: Position) -> float:
    if position == Position.SB:
        return SMALL_BLIND
    if position == Position.BB:
        return BIG_BLIND
    return 0.0


def _dead_blinds(*seated: Position) -> float:
    """
    Blinds belonging to nobody in the hand so far.

    A blind posted by hero or by a villain is already counted inside that
    player's invested amount, so counting it again would inflate the pot.
    """
    return sum(
        blind for position in (Position.SB, Position.BB)
        if (blind := blind_posted(position)) and position not in seated
    )


def sizings_for(metadata: dict) -> dict:
    """A chart's sizings, with defaults filled in for anything it omits."""
    return {**DEFAULT_SIZINGS, **(metadata.get("sizings") or {})}


def build_node(metadata: dict) -> Node:
    """Resolve a chart's metadata into a concrete preflop spot."""
    situation = metadata.get("situation")
    hero = Position(metadata["hero_position"])
    sizes = sizings_for(metadata)

    if situation == "RFI":
        return _rfi(hero)
    if situation == "vs_RFI":
        return _vs_rfi(hero, Position(metadata["villain_position"]), sizes)
    if situation == "vs_3Bet":
        return _vs_3bet(hero, Position(metadata["villain_position"]), sizes)
    if situation == "vs_4Bet":
        return _vs_4bet(hero, Position(metadata["villain_position"]), sizes)
    if situation == "vs_5Bet":
        return _vs_5bet(hero, Position(metadata["villain_position"]), sizes)
    if situation == "squeeze":
        return _squeeze(
            hero,
            Position(metadata["opener_position"]),
            Position(metadata["caller_position"]),
            sizes,
        )
    raise UnknownSituation(f"no node definition for situation {situation!r}")


def _rfi(hero: Position) -> Node:
    """Folded to hero. Calling here means limping for the big blind."""
    posted = blind_posted(hero)
    return Node(
        situation="RFI",
        hero_position=hero,
        actions_before_hero=[],
        hero_invested_bb=posted,
        pot_bb=SMALL_BLIND + BIG_BLIND,
        to_call_bb=max(BIG_BLIND - posted, 0.0),
        raise_label="Open",
        action_text="Folded to you - open?",
    )


def _vs_rfi(hero: Position, villain: Position, sizes: dict) -> Node:
    open_bb = sizes["open_bb"]
    posted = blind_posted(hero)
    return Node(
        situation="vs_RFI",
        hero_position=hero,
        actions_before_hero=[PreflopAction(villain, Action.RAISE, open_bb)],
        hero_invested_bb=posted,
        pot_bb=_dead_blinds(hero, villain) + open_bb + posted,
        to_call_bb=open_bb - posted,
        raise_label="3-Bet",
        action_text=f"{villain} opens {_bb(open_bb)}",
    )


def _vs_3bet(hero: Position, villain: Position, sizes: dict) -> Node:
    """Hero opened, villain 3-bet."""
    open_bb, three_bet = sizes["open_bb"], sizes["3bet_bb"]
    return Node(
        situation="vs_3Bet",
        hero_position=hero,
        actions_before_hero=[PreflopAction(villain, Action.RAISE, three_bet)],
        hero_invested_bb=open_bb,
        pot_bb=_dead_blinds(hero, villain) + open_bb + three_bet,
        to_call_bb=three_bet - open_bb,
        raise_label="4-Bet",
        action_text=f"You open {_bb(open_bb)}, {villain} 3-bets {_bb(three_bet)}",
    )


def _vs_4bet(hero: Position, villain: Position, sizes: dict) -> Node:
    """Villain opened, hero 3-bet, villain 4-bet."""
    open_bb, three_bet, four_bet = sizes["open_bb"], sizes["3bet_bb"], sizes["4bet_bb"]
    return Node(
        situation="vs_4Bet",
        hero_position=hero,
        actions_before_hero=[PreflopAction(villain, Action.RAISE, four_bet)],
        hero_invested_bb=three_bet,
        pot_bb=_dead_blinds(hero, villain) + three_bet + four_bet,
        to_call_bb=four_bet - three_bet,
        raise_label="5-Bet Jam",
        action_text=(
            f"{villain} opens {_bb(open_bb)}, you 3-bet {_bb(three_bet)}, "
            f"{villain} 4-bets {_bb(four_bet)}"
        ),
    )


def _vs_5bet(hero: Position, villain: Position, sizes: dict) -> Node:
    """Hero opened, villain 3-bet, hero 4-bet, villain 5-bet."""
    open_bb, three_bet = sizes["open_bb"], sizes["3bet_bb"]
    four_bet, five_bet = sizes["4bet_bb"], sizes["5bet_bb"]
    return Node(
        situation="vs_5Bet",
        hero_position=hero,
        actions_before_hero=[PreflopAction(villain, Action.RAISE, five_bet)],
        hero_invested_bb=four_bet,
        pot_bb=_dead_blinds(hero, villain) + four_bet + five_bet,
        to_call_bb=five_bet - four_bet,
        raise_label="Call All-In",
        action_text=(
            f"You open {_bb(open_bb)}, {villain} 3-bets {_bb(three_bet)}, "
            f"you 4-bet {_bb(four_bet)}, {villain} 5-bets {_bb(five_bet)}"
        ),
    )


def _squeeze(hero: Position, opener: Position, caller: Position, sizes: dict) -> Node:
    open_bb = sizes["open_bb"]
    posted = blind_posted(hero)
    return Node(
        situation="squeeze",
        hero_position=hero,
        actions_before_hero=[
            PreflopAction(opener, Action.RAISE, open_bb),
            PreflopAction(caller, Action.CALL, open_bb),
        ],
        hero_invested_bb=posted,
        pot_bb=_dead_blinds(hero, opener, caller) + open_bb * 2 + posted,
        to_call_bb=open_bb - posted,
        raise_label="Squeeze",
        action_text=f"{opener} opens {_bb(open_bb)}, {caller} calls",
    )


def _bb(amount: float) -> str:
    return f"{amount:g}bb"


def build_scenario(metadata: dict, hand: Hand, chart_key: str) -> TrainingScenario:
    """Build the scenario the user is shown, from a chart's metadata."""
    node = build_node(metadata)
    return TrainingScenario(
        table_size=int(metadata["table_size"]),
        effective_stack_bb=int(metadata["stack_depth"]),
        hero_position=node.hero_position,
        hero_hand=hand,
        actions_before_hero=node.actions_before_hero,
        chart_key=chart_key,
        situation=node.situation,
        hero_invested_bb=node.hero_invested_bb,
        pot_bb=node.pot_bb,
        to_call_bb=node.to_call_bb,
        raise_label=node.raise_label,
        action_text=node.action_text,
    )

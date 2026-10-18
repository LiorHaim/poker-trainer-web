"""
Data classes for all poker-related logic.
This version is upgraded to handle "vs_4Bet" scenarios.
"""
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# --- (Card, Hand, Deck, Position, Action, Street... classes are unchanged) ---
RANKS = "23456789TJQKA"
SUITS = "cdhs" # clubs, diamonds, hearts, spades

@dataclass(frozen=True, order=True)
class Card:
    rank: str
    suit: str
    def __post_init__(self):
        if self.rank not in RANKS: raise ValueError(f"Invalid rank: {self.rank}")
        if self.suit not in SUITS: raise ValueError(f"Invalid suit: {self.suit}")
    def __repr__(self): return f"{self.rank}{self.suit}"
    @property
    def rank_value(self) -> int: return RANKS.index(self.rank)

@dataclass(frozen=True)
class Hand:
    card1: Card
    card2: Card
    @classmethod
    def from_str(cls, hand_str: str) -> 'Hand':
        if len(hand_str) != 4: raise ValueError("Hand string must be 4 chars (e.g., 'AhKs')")
        c1 = Card(hand_str[0], hand_str[1]); c2 = Card(hand_str[2], hand_str[3])
        return cls(card1=c1, card2=c2)
    @property
    def range_notation(self) -> str:
        c1, c2 = sorted([self.card1, self.card2], key=lambda c: c.rank_value, reverse=True)
        if c1.rank == c2.rank: return f"{c1.rank}{c2.rank}"
        if c1.suit == c2.suit: return f"{c1.rank}{c2.rank}s"
        return f"{c1.rank}{c2.rank}o"

FULL_DECK = tuple(Card(rank, suit) for rank in RANKS for suit in SUITS)
def get_random_hand() -> Hand:
    card1, card2 = random.sample(FULL_DECK, 2)
    return Hand(card1, card2)

def random_hand_of(notation: str) -> Hand:
    """
    Deal a concrete hand of a given class: "AKs" -> Ah Kh, A<>K of one suit.

    Dealing from a restricted range means choosing the class first and then a
    combination of it, rather than drawing two cards from the deck.
    """
    high, low = notation[0], notation[1]
    suffix = notation[2:]
    if high == low:
        suit1, suit2 = random.sample(SUITS, 2)
    elif suffix == "s":
        suit1 = suit2 = random.choice(SUITS)
    elif suffix == "o":
        suit1, suit2 = random.sample(SUITS, 2)
    else:
        raise ValueError(f"{notation!r} is not canonical hand notation")
    return Hand(Card(high, suit1), Card(low, suit2))

class Position(Enum):
    UTG = "UTG"; MP = "MP"; CO = "CO"; BTN = "BTN"; SB = "SB"; BB = "BB"
    def __str__(self): return self.value

class Action(Enum):
    FOLD = "FOLD"; CALL = "CALL"; RAISE = "RAISE"
    def __str__(self): return self.value

class Street(Enum):
    PREFLOP = "PREFLOP"; FLOP = "FLOP"; TURN = "TURN"; RIVER = "RIVER"

@dataclass
class PreflopAction:
    position: Position
    action: Action
    size_bb: float = 0

@dataclass
class TrainingScenario:
    """
    A complete, self-contained preflop scenario for the user to solve.

    The money in play is computed once by `logic.nodes.build_scenario` from the
    chart's declared sizings, and carried here as plain numbers. It used to be
    derived by properties on this class from a table of hardcoded pot sizes,
    which disagreed with the sizes the charts were actually built for.
    """
    table_size: int = 6
    effective_stack_bb: int = 100
    hero_position: Position = Position.BTN
    hero_hand: Hand = field(default_factory=get_random_hand)
    actions_before_hero: list[PreflopAction] = field(default_factory=list)
    chart_key: str = ""
    situation: str = "RFI"

    #: What hero already has in the pot: a posted blind, or an earlier raise.
    hero_invested_bb: float = 0.0
    #: Total pot before hero acts, and what hero must add to continue.
    pot_bb: float = 1.5
    to_call_bb: float = 0.0

    #: What the raise button does here, and the one-line description of the
    #: action so far. Generated server-side so the UI has a single source.
    raise_label: str = "Raise"
    action_text: str = ""


# --- Training Result ---
@dataclass
class TrainingResult:
    scenario: TrainingScenario
    user_action: Action
    correct_action: Action
    explanation: str
    is_correct: bool
    compiled_chart: dict[str, Any]

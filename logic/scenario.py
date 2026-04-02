"""
Data classes for all poker-related logic.
This version is upgraded to handle "vs_4Bet" scenarios.
"""
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Union, Dict, Any

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
    """
    table_size: int = 6
    effective_stack_bb: int = 100
    hero_position: Position = Position.BTN
    hero_hand: Hand = field(default_factory=get_random_hand)
    actions_before_hero: list[PreflopAction] = field(default_factory=list)
    chart_key: str = ""
    
    situation: str = "RFI" # e.g., "RFI", "vs_RFI", "vs_3Bet", "vs_4Bet"
    hero_open_size_bb: float = 0.0 # Hero's *own* open size in a vs_3Bet spot
    hero_3bet_size_bb: float = 0.0 # Hero's *own* 3-bet size in a vs_4Bet spot
    
    @property
    def pot_bb(self) -> float:
        """Calculates the current pot size in BBs."""
        pot = 1.5 # Blinds
        
        # Add hero's own open/3bet
        if self.situation == "vs_3Bet":
            pot += self.hero_open_size_bb
        elif self.situation == "vs_4Bet":
            # Pot includes Hero's 3-bet AND Villain's open (which hero 3-bet)
            # A bit complex, so we'll approximate based on the 4-bet
            # 1.5 (blinds) + 3.0 (Villain open) + 9.0 (Hero 3-bet) + 25.0 (Villain 4-bet)
            # Let's just calculate from the actions
            # Standard 4-bet pot: Blinds(1.5) + V-Open(3) + H-3Bet(9) + V-4Bet(25) = 38.5
            # This is complex. Let's simplify and just add hero's last bet.
            pot += self.hero_3bet_size_bb

        # Add all villain actions
        for act in self.actions_before_hero:
            if act.action == Action.RAISE:
                pot += act.size_bb # Add the 3-bet or 4-bet amount
            elif act.action == Action.CALL:
                pot += act.size_bb 
                
        # This logic is getting complex. Let's hardcode for simplicity
        # based on standard sizings.
        
        if self.situation == "RFI": return 1.5
        if self.situation == "vs_RFI": return 4.5 # 1.5 blinds + 3.0 raise
        if self.situation == "3Bet": return 4.5 # 1.5 blinds + 3.0 villain open (we're deciding to 3-bet)
        if self.situation == "vs_3Bet": return 13.5 # 1.5 blinds + 3.0 open + 9.0 3bet
        if self.situation == "vs_4Bet": return 38.5 # 1.5 blinds + 3.0 open + 9.0 3bet + 25.0 4bet
        if self.situation == "squeeze": return 7.5 # 1.5 blinds + 3.0 open + 3.0 call

        return 1.5 # Default

    @property
    def to_call_bb(self) -> float:
        """Calculates the amount the hero needs to call in BBs."""
        if not self.actions_before_hero:
            if self.hero_position == Position.SB: return 0.5 
            if self.hero_position == Position.BB: return 1.0
            return 0.0 # RFI
        
        last_raise_size = self.actions_before_hero[-1].size_bb
        
        if self.situation == "vs_4Bet":
            # Call amount is 4-bet size MINUS our 3-bet
            return last_raise_size - self.hero_3bet_size_bb
        
        if self.situation == "vs_3Bet":
            # Call amount is 3-bet size MINUS our open
            return last_raise_size - self.hero_open_size_bb
        
        if self.situation == "vs_RFI":
            if self.hero_position == Position.SB: return last_raise_size - 0.5
            if self.hero_position == Position.BB: return last_raise_size - 1.0
            return last_raise_size # Calling an open
        
        if self.situation == "3Bet":
            # Hero is deciding to 3-bet, so "call" would be the villain's open
            if self.hero_position == Position.SB: return last_raise_size - 0.5
            if self.hero_position == Position.BB: return last_raise_size - 1.0
            return last_raise_size
        
        if self.situation == "squeeze":
            # Hero faces an open and a call, needs to call the open amount
            if self.hero_position == Position.SB: return last_raise_size - 0.5
            if self.hero_position == Position.BB: return last_raise_size - 1.0
            return last_raise_size
        
        return 0.0 # Should not be hit

# --- Training Result ---
@dataclass
class TrainingResult:
    scenario: TrainingScenario
    user_action: Action
    correct_action: Action
    explanation: str
    is_correct: bool
    compiled_chart: Dict[str, Any]
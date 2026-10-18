"""
Unit tests for the core logic modules.
This is critical to ensure our poker rules are correct before we
even touch the GUI.
"""
import sys
import unittest
from pathlib import Path

# Add parent directory to path to import logic module
sys.path.insert(0, str(Path(__file__).parent.parent))

from logic.scenario import Hand


class TestHandLogic(unittest.TestCase):

    def test_hand_from_str(self):
        """Tests creating a Hand from a string."""
        hand = Hand.from_str("AsKh")
        self.assertEqual(hand.card1.rank, "A")
        self.assertEqual(hand.card1.suit, "s")
        self.assertEqual(hand.card2.rank, "K")
        self.assertEqual(hand.card2.suit, "h")

    def test_range_notation_pocket_pair(self):
        """Tests pocket pair notation (e.g., 'AA')."""
        hand = Hand.from_str("AdAc")
        self.assertEqual(hand.range_notation, "AA")

        # Test rank order
        hand_rev = Hand.from_str("AcAd")
        self.assertEqual(hand_rev.range_notation, "AA")

    def test_range_notation_suited(self):
        """Tests suited hand notation (e.g., 'AKs')."""
        hand = Hand.from_str("KsQs")
        self.assertEqual(hand.range_notation, "KQs")

        # Test rank order
        hand_rev = Hand.from_str("QsKs")
        self.assertEqual(hand_rev.range_notation, "KQs")

    def test_range_notation_offsuit(self):
        """Tests offsuit hand notation (e.g., 'AKo')."""
        hand = Hand.from_str("AhKc")
        self.assertEqual(hand.range_notation, "AKo")

        # Test rank order
        hand_rev = Hand.from_str("KcAh")
        self.assertEqual(hand_rev.range_notation, "AKo")

if __name__ == '__main__':
    unittest.main()

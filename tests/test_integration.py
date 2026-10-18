import sys
import unittest
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from logic.strategy import StrategyManager
from logic.trainer import TrainingEngine


class MockStatsManager:
    """Mock for testing without DB"""
    def log_decision(self, result, username): pass
    def get_bankroll(self, username): return 10000

class TestIntegration(unittest.TestCase):
    def setUp(self):
        # Path to actual strategy charts
        self.charts_path = Path(__file__).parent.parent / "strategy_charts"
        self.strategy_mgr = StrategyManager(self.charts_path)
        self.stats_mgr = MockStatsManager()
        self.trainer = TrainingEngine(self.strategy_mgr, self.stats_mgr)

    def test_charts_loading(self):
        """Ensure all charts load without error"""
        self.assertTrue(len(self.strategy_mgr.charts) > 0, "No charts loaded")
        print(f"\nLoaded {len(self.strategy_mgr.charts)} charts.")

    def test_scenario_generation(self):
        """Test generating scenarios for different modes"""
        settings = {
            "game_type": "Cash Game",
            "table_size": 6,
            "stack_depths": [100],
            "training_mode": "Drill"
        }
        self.trainer.configure_training(settings)

        # Try generating 100 scenarios to catch any edge case errors
        for _ in range(100):
            sc = self.trainer.get_next_scenario()
            self.assertIsNotNone(sc, "Failed to generate scenario")
            self.assertTrue(sc.chart_key in self.strategy_mgr.charts, "Scenario uses unknown chart")

    def test_specific_situations(self):
        """Test that we can filter by situation (implicit via metadata)"""
        # This tests the 'Focus' mode logic indirectly
        settings = {
            "training_mode": "Focus",
            "focus_position": "BTN"
        }
        self.trainer.configure_training(settings)
        sc = self.trainer.get_next_scenario()
        if sc:
            self.assertEqual(sc.hero_position.value, "BTN")

if __name__ == '__main__':
    unittest.main()

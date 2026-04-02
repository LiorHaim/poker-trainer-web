"""
The Strategy Manager - The "Poker Brain"

This module loads and parses the strategy JSON files from the
`strategy_charts/` directory. It provides a simple API for the
TrainingEngine to query the correct action for a given hand.
"""
import json
import os
import logging
from pathlib import Path
from typing import Union, Dict, Any
from .scenario import Hand, Action

logger = logging.getLogger(__name__)

class StrategyManager:
    """Loads and manages all preflop strategy charts."""
    
    def __init__(self, charts_directory: Union[str, Path]):
        self.charts_directory = Path(charts_directory)
        self.charts: Dict[str, Any] = {}
        self.chart_metadata: Dict[str, Any] = {}
        self.load_charts()

    def load_charts(self):
        """Loads all .json files from the strategy directory."""
        if not self.charts_directory.is_dir():
            logger.warning(f"Strategy directory not found: {self.charts_directory}")
            return

        for file_path in self.charts_directory.glob("*.json"):
            try:
                with open(file_path, 'r') as f:
                    chart_data = json.load(f)
                    chart_key = file_path.stem
                    
                    self.chart_metadata[chart_key] = chart_data.get("metadata", {})
                    self.charts[chart_key] = self._compile_chart(chart_data)
                    logger.info(f"Loaded chart: {chart_key}")
                    
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON in {file_path}")
            except Exception as e:
                logger.error(f"Failed to load chart {file_path}: {e}")

    def _compile_chart(self, chart_data: dict) -> dict:
        """
        Converts the "range-first" JSON structure into a "hand-first"
        dict for O(1) lookups.
        
        From: { "RAISE": ["AA", "KK"], "FOLD": ["72o"] }
        To:   { "AA": "RAISE", "KK": "RAISE", "72o": "FOLD" }
        """
        compiled_chart = {}
        meta = chart_data.get("metadata", {})
        actions = chart_data.get("actions", {})

        for action_str, hands_list in actions.items():
            try:
                action_enum = Action[action_str.upper()]
            except KeyError:
                logger.warning(f"Unknown action '{action_str}' in chart, skipping")
                continue
            for hand_range in hands_list:
                compiled_chart[hand_range] = {
                    "action": action_enum,
                    "explanation": meta.get("explanations", {}).get(action_str, "No explanation provided.")
                }
        
        return compiled_chart

    def get_recommended_action(self, situation_key: str, hand: Hand) -> Union[dict, None]:
        """Gets the recommended action for a specific hand in a specific situation."""
        chart = self.charts.get(situation_key)
        if not chart:
            logger.warning(f"No strategy chart found for key: {situation_key}")
            return None
            
        hand_notation = hand.range_notation
        action_data = chart.get(hand_notation)
        
        if not action_data:
            return {"action": Action.FOLD, "explanation": "This hand is not in the strategy chart, defaulting to FOLD."}
            
        return action_data

    def get_compiled_chart(self, chart_key: str) -> Union[Dict[str, Any], None]:
        """Returns the entire compiled chart for a given key."""
        return self.charts.get(chart_key)

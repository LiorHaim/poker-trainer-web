# ... (Imports remain the same)
import random
from typing import Any

from .scenario import Action, Position, PreflopAction, TrainingResult, TrainingScenario, get_random_hand
from .statistics_db import StatisticsManagerDB
from .strategy import StrategyManager


class TrainingEngine:
    def __init__(self, strategy_manager: StrategyManager, stats_manager: StatisticsManagerDB):
        self.strategy_manager = strategy_manager
        self.stats_manager = stats_manager
        self.current_scenario: TrainingScenario | None = None
        self.available_scenarios: list[dict[str, Any]] = []
        self.game_type_prefix = "cash"

    def configure_training(self, settings: dict):
        """Configure training based on user settings with optional position and situation filters."""
        self.available_scenarios.clear()
        self.game_type_prefix = "cash" if settings.get("game_type") == "Cash Game" else "mtt"
        table_size = int(settings.get("table_size", 6))
        stack_depths = [int(x) for x in settings.get("stack_depths", [100])]
        mode = settings.get("training_mode", "Drill")
        focus_pos = settings.get("focus_position")
        focus_situation = settings.get("focus_situation")
        if hasattr(focus_pos, 'value'): focus_pos = focus_pos.value

        for key, meta in self.strategy_manager.chart_metadata.items():
            if meta.get("game_type") != self.game_type_prefix: continue
            if int(meta.get("table_size", 0)) != table_size: continue
            if int(meta.get("stack_depth", 0)) not in stack_depths: continue

            # Filter by position if specified
            if mode == "Focus" and focus_pos and str(meta.get("hero_position")) != str(focus_pos): continue

            # Filter by situation if specified
            if mode == "Focus" and focus_situation and str(meta.get("situation")) != str(focus_situation): continue

            meta['chart_key'] = key
            self.available_scenarios.append(meta)

    def get_next_scenario(self) -> TrainingScenario | None:
        # ... (This method is unchanged, uses current_scenario logic) ...
        if not self.available_scenarios: return None
        scenario_meta = random.choice(self.available_scenarios)
        hand = get_random_hand()
        chart_key = scenario_meta["chart_key"]
        situation = scenario_meta.get("situation", "RFI")
        actions_before_hero = []
        hero_open_size = 0.0; hero_3bet_size = 0.0

        try:
            if situation == "vs_RFI":
                villain_pos = Position(scenario_meta["villain_position"])
                actions_before_hero = [PreflopAction(position=villain_pos, action=Action.RAISE, size_bb=3.0)]
            elif situation == "vs_3Bet":
                villain_pos = Position(scenario_meta["villain_position"])
                hero_open_size = 3.0
                actions_before_hero = [PreflopAction(position=villain_pos, action=Action.RAISE, size_bb=9.0)]
            elif situation == "vs_4Bet":
                villain_pos = Position(scenario_meta["villain_position"])
                hero_open_size = 3.0; hero_3bet_size = 9.0
                actions_before_hero = [PreflopAction(position=villain_pos, action=Action.RAISE, size_bb=25.0)]
            elif situation == "squeeze":
                opener_pos = Position(scenario_meta["opener_position"])
                caller_pos = Position(scenario_meta["caller_position"])
                actions_before_hero = [
                    PreflopAction(position=opener_pos, action=Action.RAISE, size_bb=3.0),
                    PreflopAction(position=caller_pos, action=Action.CALL, size_bb=3.0)
                ]
            elif situation == "3Bet":
                # Hero is in SB/BB deciding to 3-bet over villain's open
                villain_pos = Position(scenario_meta["villain_position"])
                actions_before_hero = [PreflopAction(position=villain_pos, action=Action.RAISE, size_bb=3.0)]
        except (KeyError, ValueError):
            situation = "RFI"
            actions_before_hero = []

        self.current_scenario = TrainingScenario(
            table_size=int(scenario_meta["table_size"]),
            effective_stack_bb=int(scenario_meta["stack_depth"]),
            hero_position=Position(scenario_meta["hero_position"]),
            hero_hand=hand,
            actions_before_hero=actions_before_hero,
            chart_key=chart_key, situation=situation,
            hero_open_size_bb=hero_open_size, hero_3bet_size_bb=hero_3bet_size
        )
        return self.current_scenario

    # --- MODIFIED: Now gets user_id from Flask App context or passed arg?
    # Actually, simpler to NOT log here and let App.py do it,
    # OR pass username. Let's remove the log_decision call here to keep Logic pure.
    def submit_user_action(self, user_action: Action) -> TrainingResult | None:
        if not self.current_scenario: return None
        chart_key = self.current_scenario.chart_key
        compiled_chart = self.strategy_manager.get_compiled_chart(chart_key)

        if not chart_key or not compiled_chart:
            return TrainingResult(self.current_scenario, user_action, Action.FOLD, "Error", False, {})

        rec_data = self.strategy_manager.get_recommended_action(chart_key, self.current_scenario.hero_hand)
        if not rec_data: rec_data = {"action": Action.FOLD, "explanation": "Error"}

        result = TrainingResult(
            scenario=self.current_scenario,
            user_action=user_action,
            correct_action=rec_data["action"],
            explanation=rec_data["explanation"],
            is_correct=(user_action == rec_data["action"]),
            compiled_chart=compiled_chart
        )

        # REMOVED: self.stats_manager.log_decision(result)
        # (We will log this in app.py where we know the username!)

        return result

"""
The Strategy Manager - The "Poker Brain"

This module loads and parses the strategy JSON files from the
`strategy_charts/` directory. It provides a simple API for the
TrainingEngine to query the correct action for a given hand.

Loading goes through `logic.chart_schema`, so a malformed chart is reported
rather than silently mangled. Set `CHART_VALIDATION=strict` to refuse to start
when any chart fails validation.
"""
import logging
import os
from pathlib import Path
from typing import Any

from .chart_schema import (
    DEFAULT_BASELINE,
    apply_baseline,
    load_baseline,
    load_charts,
)
from .chart_schema import (
    errors as error_issues,
)
from .chart_schema import (
    warnings as warning_issues,
)
from .scenario import Action, Hand

logger = logging.getLogger(__name__)


class ChartValidationError(RuntimeError):
    """Raised in strict mode when a chart fails validation."""


def _group_by_code(issues):
    """Collapse issues by code so one problem shared by every chart logs as one line."""
    grouped: dict[str, list] = {}
    for issue in issues:
        grouped.setdefault(issue.code, []).append(issue)
    return grouped


class StrategyManager:
    """Loads and manages all preflop strategy charts."""

    def __init__(self, charts_directory: str | Path, strict: bool | None = None):
        self.charts_directory = Path(charts_directory)
        self.charts: dict[str, Any] = {}
        self.chart_metadata: dict[str, Any] = {}
        if strict is None:
            strict = os.environ.get("CHART_VALIDATION", "").lower() == "strict"
        self.strict = strict
        self.load_charts()

    def load_charts(self):
        """Load, validate, and compile every chart in the strategy directory."""
        documents, issues = load_charts(self.charts_directory)
        result = apply_baseline(issues, load_baseline(DEFAULT_BASELINE))

        new_errors = error_issues(result.new)
        new_warnings = warning_issues(result.new)
        for issue in new_errors:
            logger.error("Chart validation: %s", issue)
        for code, group in _group_by_code(new_warnings).items():
            if len(group) == 1:
                logger.warning("Chart validation: %s", group[0])
            else:
                logger.warning(
                    "Chart validation: %s affects %d charts - %s", code, len(group), group[0].message
                )
        if result.known:
            logger.info(
                "Chart validation: %d known issues suppressed (see CHART_KNOWN_ISSUES.json)",
                len(result.known),
            )

        if new_errors and self.strict:
            raise ChartValidationError(
                f"{len(new_errors)} chart validation error(s); refusing to start in strict mode"
            )

        for chart_key, chart_data in documents.items():
            self.chart_metadata[chart_key] = chart_data.get("metadata", {})
            self.charts[chart_key] = self._compile_chart(chart_data)

        logger.info(
            "Loaded %d charts (%d errors, %d warnings, %d known issues)",
            len(self.charts),
            len(new_errors),
            len(new_warnings),
            len(result.known),
        )

    def _compile_chart(self, chart_data: dict) -> dict:
        """
        Converts the "range-first" JSON structure into a "hand-first"
        dict for O(1) lookups.

        From: { "RAISE": ["AA", "KK"], "FOLD": ["72o"] }
        To:   { "AA": "RAISE", "KK": "RAISE", "72o": "FOLD" }

        A hand assigned to two actions is a validation error, reported at load
        time rather than resolved here by dict ordering.
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
                    "explanation": meta.get("explanations", {}).get(action_str, "No explanation provided."),
                }

        return compiled_chart

    def get_recommended_action(self, situation_key: str, hand: Hand) -> dict | None:
        """Gets the recommended action for a specific hand in a specific situation."""
        chart = self.charts.get(situation_key)
        if not chart:
            logger.warning(f"No strategy chart found for key: {situation_key}")
            return None

        hand_notation = hand.range_notation
        action_data = chart.get(hand_notation)

        if not action_data:
            # Validation guarantees full coverage, so reaching this means a chart
            # regressed. Log it loudly instead of quietly teaching a fold.
            logger.error(
                "Chart %s has no entry for %s; defaulting to FOLD", situation_key, hand_notation
            )
            return {"action": Action.FOLD, "explanation": "This hand is not in the strategy chart, defaulting to FOLD."}

        return action_data

    def get_compiled_chart(self, chart_key: str) -> dict[str, Any] | None:
        """Returns the entire compiled chart for a given key."""
        return self.charts.get(chart_key)

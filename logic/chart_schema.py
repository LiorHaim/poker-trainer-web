"""
Strategy chart schema and validation.

Every file in `strategy_charts/` is a preflop decision node: a position, a
situation, and an action for each of the 169 starting hands. Nothing used to
check that those files were well formed, so a hand listed under two actions, a
missing hand, or two charts describing the same decision all failed silently at
runtime.

This module is the single definition of what a valid chart is. It is used by
`StrategyManager` at load time, by `scripts/validate_charts.py` in CI, and by
`tests/test_chart_invariants.py`.

Two levels of checking:

* `validate_chart`      - one chart on its own (structure, coverage, duplicates)
* `validate_chart_set`  - all charts together (duplicate decision nodes, hands
                          that cannot reach the node they are listed under)

See `docs/CHART_SCHEMA.md` for the format itself.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# --- Vocabulary -------------------------------------------------------------

RANKS = "AKQJT98765432"
POSITIONS = ("UTG", "MP", "CO", "BTN", "SB", "BB")
ACTIONS = ("FOLD", "CALL", "RAISE")
GAME_TYPES = ("cash", "mtt")
SITUATIONS = ("RFI", "vs_RFI", "3Bet", "vs_3Bet", "vs_4Bet", "squeeze")

#: Positions in order of action preflop. Used to sanity check who can face whom.
POSITION_ORDER = {pos: i for i, pos in enumerate(POSITIONS)}


def _all_hands() -> frozenset[str]:
    hands = set()
    for i, high in enumerate(RANKS):
        for j, low in enumerate(RANKS):
            if i == j:
                hands.add(high + low)
            elif i < j:
                hands.add(f"{high}{low}s")
                hands.add(f"{high}{low}o")
    return frozenset(hands)


#: The 169 canonical starting hands ("AA", "AKs", "AKo", ...).
ALL_HANDS = _all_hands()

#: Metadata keys every chart must define.
REQUIRED_METADATA = (
    "chart_id",
    "description",
    "game_type",
    "table_size",
    "stack_depth",
    "hero_position",
    "situation",
    "explanations",
)

#: Extra metadata keys required for particular situations.
SITUATION_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "RFI": (),
    "vs_RFI": ("villain_position",),
    "3Bet": ("villain_position",),
    "vs_3Bet": ("villain_position",),
    "vs_4Bet": ("villain_position",),
    "squeeze": ("opener_position", "caller_position"),
}

#: Optional `metadata.sizings` keys, in bb. Validated when present; will become
#: required in phase 1, when the engine stops hardcoding 3.0bb for every open.
SIZING_KEYS = ("open_bb", "3bet_bb", "4bet_bb", "5bet_bb", "call_bb")


# --- Issues -----------------------------------------------------------------

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class ChartIssue:
    """A single validation finding, tied to the chart that produced it."""

    chart: str
    code: str
    severity: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.upper():7}] {self.chart}: {self.code} - {self.message}"


def errors(issues: Iterable[ChartIssue]) -> list[ChartIssue]:
    return [i for i in issues if i.severity == ERROR]


def warnings(issues: Iterable[ChartIssue]) -> list[ChartIssue]:
    return [i for i in issues if i.severity == WARNING]


def format_issues(issues: Iterable[ChartIssue]) -> str:
    return "\n".join(str(i) for i in issues)


# --- Hand notation ----------------------------------------------------------

def is_valid_hand(hand: Any) -> bool:
    """True for canonical notation: 'AA', 'AKs', 'AKo'. Order matters: 'KAs' is not valid."""
    return isinstance(hand, str) and hand in ALL_HANDS


# --- Single chart -----------------------------------------------------------

def validate_chart(chart_key: str, data: Any) -> list[ChartIssue]:
    """Validate one chart document. Returns every issue found, worst case first."""
    issues: list[ChartIssue] = []

    def err(code: str, message: str) -> None:
        issues.append(ChartIssue(chart_key, code, ERROR, message))

    def warn(code: str, message: str) -> None:
        issues.append(ChartIssue(chart_key, code, WARNING, message))

    if not isinstance(data, dict):
        err("not-an-object", f"expected a JSON object, got {type(data).__name__}")
        return issues

    meta = data.get("metadata")
    if not isinstance(meta, dict):
        err("missing-metadata", "`metadata` is missing or not an object")
        meta = {}

    actions = data.get("actions")
    if not isinstance(actions, dict) or not actions:
        err("missing-actions", "`actions` is missing, empty, or not an object")
        return issues

    issues += _validate_metadata(chart_key, meta)
    issues += _validate_actions(chart_key, meta, actions)
    return issues


def _validate_metadata(chart_key: str, meta: dict) -> list[ChartIssue]:
    issues: list[ChartIssue] = []

    def err(code: str, message: str) -> None:
        issues.append(ChartIssue(chart_key, code, ERROR, message))

    def warn(code: str, message: str) -> None:
        issues.append(ChartIssue(chart_key, code, WARNING, message))

    for key in REQUIRED_METADATA:
        if key not in meta:
            err("missing-metadata-key", f"metadata.{key} is required")

    chart_id = meta.get("chart_id")
    if chart_id is not None and chart_id != chart_key:
        err(
            "chart-id-mismatch",
            f"metadata.chart_id is {chart_id!r} but the file is named {chart_key!r}",
        )

    game_type = meta.get("game_type")
    if game_type is not None and game_type not in GAME_TYPES:
        err("bad-game-type", f"game_type {game_type!r} is not one of {GAME_TYPES}")

    for key in ("table_size", "stack_depth"):
        value = meta.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            err("bad-metadata-type", f"metadata.{key} must be an integer, got {value!r}")
        elif isinstance(value, int) and value <= 0:
            err("bad-metadata-value", f"metadata.{key} must be positive, got {value}")

    hero = meta.get("hero_position")
    if hero is not None and hero not in POSITIONS:
        err("bad-position", f"hero_position {hero!r} is not one of {POSITIONS}")

    situation = meta.get("situation")
    if situation is None:
        pass  # already reported as a missing key
    elif situation not in SITUATIONS:
        err("bad-situation", f"situation {situation!r} is not one of {SITUATIONS}")
    else:
        for key in SITUATION_REQUIREMENTS[situation]:
            value = meta.get(key)
            if value is None:
                err("missing-metadata-key", f"metadata.{key} is required for situation {situation!r}")
            elif value not in POSITIONS:
                err("bad-position", f"metadata.{key} is {value!r}, not one of {POSITIONS}")
            elif value == hero:
                err("self-villain", f"metadata.{key} is {value!r}, the same seat as hero")

    explanations = meta.get("explanations")
    if explanations is not None and not isinstance(explanations, dict):
        err("bad-explanations", "metadata.explanations must be an object keyed by action")

    sizings = meta.get("sizings")
    if sizings is None:
        warn(
            "missing-sizings",
            "metadata.sizings is absent; the engine falls back to hardcoded sizes, "
            "so the pot odds shown to the user may not match this chart",
        )
    elif not isinstance(sizings, dict):
        err("bad-sizings", "metadata.sizings must be an object")
    else:
        for key, value in sizings.items():
            if key not in SIZING_KEYS:
                warn("unknown-sizing", f"metadata.sizings.{key} is not a recognised key {SIZING_KEYS}")
            elif isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
                err("bad-sizing-value", f"metadata.sizings.{key} must be a positive number, got {value!r}")

    return issues


def _validate_actions(chart_key: str, meta: dict, actions: dict) -> list[ChartIssue]:
    issues: list[ChartIssue] = []

    def err(code: str, message: str) -> None:
        issues.append(ChartIssue(chart_key, code, ERROR, message))

    def warn(code: str, message: str) -> None:
        issues.append(ChartIssue(chart_key, code, WARNING, message))

    explanations = meta.get("explanations") if isinstance(meta.get("explanations"), dict) else {}
    assignments: dict[str, list[str]] = {}

    for action, hands in actions.items():
        if action not in ACTIONS:
            err("bad-action", f"action {action!r} is not one of {ACTIONS}")
            continue
        if not isinstance(hands, list):
            err("bad-action-list", f"actions.{action} must be a list of hands")
            continue
        if action not in explanations:
            err("missing-explanation", f"metadata.explanations.{action} is required because {action} is used")

        seen_here: set[str] = set()
        for hand in hands:
            if not is_valid_hand(hand):
                err("bad-hand", f"{hand!r} under {action} is not canonical hand notation")
                continue
            if hand in seen_here:
                err("repeated-hand", f"{hand} is listed twice under {action}")
            seen_here.add(hand)
            assignments.setdefault(hand, []).append(action)

    for hand, assigned in sorted(assignments.items()):
        if len(assigned) > 1:
            err(
                "duplicate-hand",
                f"{hand} is assigned to {' and '.join(assigned)}; the loader would "
                f"silently keep {assigned[-1]}",
            )

    missing = ALL_HANDS - set(assignments)
    if missing:
        err(
            "incomplete-coverage",
            f"{len(missing)} of 169 hands have no action: {_sample(missing)}",
        )

    for action in explanations:
        if action in ACTIONS and action not in actions:
            warn("unused-explanation", f"metadata.explanations.{action} is set but {action} is never used")

    return issues


def _sample(hands: Iterable[str], limit: int = 8) -> str:
    ordered = sorted(hands)
    shown = ", ".join(ordered[:limit])
    return shown if len(ordered) <= limit else f"{shown}, ... (+{len(ordered) - limit} more)"


# --- Cross-chart ------------------------------------------------------------

def decision_node_id(meta: dict) -> tuple | None:
    """
    Identify the decision node a chart models, so two charts describing the same
    decision can be detected.

    `vs_RFI` and `3Bet` are deliberately mapped to the same node: both are "hero
    faces an open and chooses fold/call/raise". The repo currently ships both for
    nine spots, with contradictory answers.
    """
    situation = meta.get("situation")
    if situation not in SITUATIONS:
        return None

    common = (meta.get("game_type"), meta.get("table_size"), meta.get("stack_depth"), meta.get("hero_position"))

    if situation in ("vs_RFI", "3Bet"):
        return (*common, "facing_open", meta.get("villain_position"))
    if situation == "squeeze":
        return (*common, "squeeze", meta.get("opener_position"), meta.get("caller_position"))
    if situation == "RFI":
        return (*common, "rfi")
    return (*common, situation, meta.get("villain_position"))


def continuing_hands(chart: dict) -> set[str]:
    """Hands this chart does something other than fold with."""
    return {
        hand
        for action, hands in chart.get("actions", {}).items()
        if action != "FOLD" and isinstance(hands, list)
        for hand in hands
        if is_valid_hand(hand)
    }


def raising_hands(chart: dict) -> set[str]:
    return {hand for hand in chart.get("actions", {}).get("RAISE", []) or [] if is_valid_hand(hand)}


def validate_chart_set(charts: dict[str, dict]) -> list[ChartIssue]:
    """
    Checks that only make sense across the whole set:

    * no two charts model the same decision node
    * at nodes only reachable through hero's own raise, every hand hero
      continues with is a hand hero would actually have raised
    """
    issues: list[ChartIssue] = []
    by_node: dict[tuple, list[str]] = {}
    rfi_by_position: dict[tuple, tuple[str, set[str]]] = {}

    for key, data in charts.items():
        meta = data.get("metadata", {})
        node = decision_node_id(meta)
        if node is not None:
            by_node.setdefault(node, []).append(key)
        if meta.get("situation") == "RFI":
            seat = (meta.get("game_type"), meta.get("table_size"), meta.get("stack_depth"), meta.get("hero_position"))
            rfi_by_position[seat] = (key, raising_hands(data))

    for _node, keys in sorted(by_node.items(), key=lambda kv: kv[1]):
        if len(keys) > 1:
            for key in sorted(keys):
                others = sorted(k for k in keys if k != key)
                issues.append(
                    ChartIssue(
                        key,
                        "duplicate-node",
                        ERROR,
                        f"models the same decision as {', '.join(others)}; "
                        f"the trainer picks one at random, so the user is taught both answers",
                    )
                )

    for key, data in sorted(charts.items()):
        meta = data.get("metadata", {})
        if meta.get("situation") not in ("vs_3Bet", "vs_4Bet"):
            continue
        seat = (meta.get("game_type"), meta.get("table_size"), meta.get("stack_depth"), meta.get("hero_position"))
        rfi = rfi_by_position.get(seat)
        if rfi is None:
            issues.append(
                ChartIssue(key, "no-rfi-chart", WARNING, f"no RFI chart for {seat[3]}, cannot check reachability")
            )
            continue
        rfi_key, opened = rfi
        unreachable = continuing_hands(data) - opened
        if unreachable:
            issues.append(
                ChartIssue(
                    key,
                    "unreachable-continue",
                    ERROR,
                    f"continues with {_sample(unreachable)}, which {rfi_key} never opens",
                )
            )

    return issues


# --- Loading ----------------------------------------------------------------

def load_charts(directory: str | Path) -> tuple[dict[str, dict], list[ChartIssue]]:
    """
    Read every chart in `directory`. Returns the parsed documents keyed by file
    stem, plus every issue found by the per-chart and cross-chart checks.

    Files that are not valid JSON are reported and skipped; everything else is
    returned even when it fails validation, so the caller decides whether a bad
    chart is fatal.
    """
    path = Path(directory)
    charts: dict[str, dict] = {}
    issues: list[ChartIssue] = []

    if not path.is_dir():
        return charts, [ChartIssue(str(path), "missing-directory", ERROR, "chart directory does not exist")]

    for file_path in sorted(path.glob("*.json")):
        chart_key = file_path.stem
        try:
            with open(file_path) as handle:
                data = json.load(handle)
        except json.JSONDecodeError as exc:
            issues.append(ChartIssue(chart_key, "invalid-json", ERROR, str(exc)))
            continue
        except OSError as exc:
            issues.append(ChartIssue(chart_key, "unreadable", ERROR, str(exc)))
            continue

        issues += validate_chart(chart_key, data)
        charts[chart_key] = data

    issues += validate_chart_set(charts)
    return charts, issues


# --- Known-issue baseline ---------------------------------------------------

#: Issues that are real, documented, and scheduled for a later phase live here
#: instead of failing CI. The validator still fails on anything new, and also
#: fails when a baseline entry stops occurring - so fixing a chart forces the
#: entry to be deleted rather than quietly rotting.
#:
#: Kept outside `strategy_charts/` so that directory contains charts and nothing else.
DEFAULT_BASELINE = Path(__file__).resolve().parent.parent / "CHART_KNOWN_ISSUES.json"


@dataclass(frozen=True)
class BaselineResult:
    new: list[ChartIssue]
    known: list[ChartIssue]
    stale: list[tuple[str, str]]


def load_baseline(path: str | Path) -> set[tuple[str, str]]:
    """Read a baseline file into a set of (chart, code) pairs."""
    baseline_path = Path(path)
    if not baseline_path.exists():
        return set()
    with open(baseline_path) as handle:
        document = json.load(handle)

    accepted: set[tuple[str, str]] = set()
    for entry in document.get("known", []):
        code = entry["code"]
        for chart in entry["charts"]:
            accepted.add((chart, code))
    return accepted


def apply_baseline(issues: Iterable[ChartIssue], baseline: set[tuple[str, str]]) -> BaselineResult:
    """Split issues into new vs already-known, and report baseline entries that no longer fire."""
    issues = list(issues)
    seen = {(i.chart, i.code) for i in issues}
    return BaselineResult(
        new=[i for i in issues if (i.chart, i.code) not in baseline],
        known=[i for i in issues if (i.chart, i.code) in baseline],
        stale=sorted(baseline - seen),
    )

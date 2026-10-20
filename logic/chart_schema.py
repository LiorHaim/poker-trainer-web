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
#: `vs_RFI` covers the whole "hero faces an open" decision, raise branch included.
#: There used to be a separate `3Bet` situation describing the same node, which
#: meant two charts per spot with conflicting answers; it was removed in phase 1.
SITUATIONS = ("RFI", "vs_RFI", "vs_3Bet", "vs_4Bet", "vs_5Bet", "squeeze")

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

#: Number of card combinations behind each hand class, and the total deck.
#: Range frequencies are quoted combo-weighted by convention: a range is "22%"
#: because it is 22% of the 1326 hands you can be dealt, not 22% of the 169
#: classes. The two differ a lot - offsuit hands are 12 combos but suited only
#: 4 - so a range that is 34% of classes can be 28% of combos.
TOTAL_COMBOS = 1326


def combo_count(hand: str) -> int:
    if len(hand) == 2:
        return 6  # pair
    return 4 if hand.endswith("s") else 12


def combo_frequency(hands: Iterable[str]) -> float:
    """Share of all 1326 dealable hands, as a percentage."""
    return 100.0 * sum(combo_count(hand) for hand in hands) / TOTAL_COMBOS

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
    "vs_3Bet": ("villain_position",),
    "vs_4Bet": ("villain_position",),
    "vs_5Bet": ("villain_position",),
    "squeeze": ("opener_position", "caller_position"),
}

#: `metadata.sizings` keys, in bb. The engine builds the spot from these, so a
#: chart drilled at the wrong size shows the user pot odds that do not match the
#: range being tested. Required since phase 1.
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
    issues += _validate_mixes(chart_key, data.get("mixes"), actions)
    return issues


def _validate_mixes(chart_key: str, mixes, actions: dict) -> list[ChartIssue]:
    """
    Check the optional `mixes` block: hands the chart plays more than one way.

    A chart assigns one action per hand, which states a hard line where real
    strategy has a gradient. `mixes` records the hands sitting on such a line,
    so a legitimate alternative is not scored as a mistake. See logic/mixes.py.
    """
    issues: list[ChartIssue] = []
    if mixes is None:
        return issues

    def err(code: str, message: str) -> None:
        issues.append(ChartIssue(chart_key, code, ERROR, message))

    if not isinstance(mixes, dict):
        err("bad-mixes", "`mixes` must be an object keyed by hand")
        return issues

    assigned = {hand: action for action, hands in actions.items()
                if isinstance(hands, list) for hand in hands}

    for hand, allowed in sorted(mixes.items()):
        if not is_valid_hand(hand):
            err("bad-mix-hand", f"{hand!r} in `mixes` is not canonical hand notation")
            continue
        if hand not in assigned:
            err("mix-without-action", f"{hand} appears in `mixes` but has no action")
            continue
        if not isinstance(allowed, list) or len(allowed) < 2:
            err("bad-mix", f"mixes.{hand} must list at least two actions")
            continue
        if len(set(allowed)) != len(allowed):
            err("repeated-mix-action", f"mixes.{hand} repeats an action")
        unknown = [a for a in allowed if a not in ACTIONS]
        if unknown:
            err("bad-mix-action", f"mixes.{hand} contains {unknown}, not in {ACTIONS}")
            continue
        if allowed[0] != assigned[hand]:
            err(
                "mix-primary-mismatch",
                f"mixes.{hand} starts with {allowed[0]} but the chart assigns "
                f"{assigned[hand]}; the chart's own action must come first",
            )
        if len(allowed) > len(ACTIONS) - 1:
            err(
                "mix-too-permissive",
                f"mixes.{hand} accepts {len(allowed)} of {len(ACTIONS)} actions, "
                f"which leaves no wrong answer",
            )

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
        err(
            "missing-sizings",
            "metadata.sizings is required; without it the engine falls back to "
            "DEFAULT_SIZINGS and the pot odds shown to the user may not match "
            "the sizes this chart's ranges were built for",
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

    Kept as a distinct concept from `situation` so that if a second way of
    describing the same decision is ever introduced again, it collides here
    rather than shipping two charts for one spot.
    """
    situation = meta.get("situation")
    if situation not in SITUATIONS:
        return None

    common = (meta.get("game_type"), meta.get("table_size"), meta.get("stack_depth"), meta.get("hero_position"))

    if situation == "vs_RFI":
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


def _seat(meta: dict) -> tuple:
    return (meta.get("game_type"), meta.get("table_size"), meta.get("stack_depth"), meta.get("hero_position"))


def prior_range_keys(meta: dict) -> tuple[tuple, ...]:
    """
    Which earlier decisions determine the hands hero can hold at this node,
    most precise first.

    Hero only arrives at a `vs_3Bet` node by opening, at `vs_4Bet` by 3-betting,
    and at `vs_5Bet` by opening *and then* 4-betting - so at those nodes hero's
    hand comes from that earlier range rather than from the whole deck. Returns
    an empty tuple where hero has not acted yet and can hold anything.

    `vs_5Bet` lists hero's opening range as a second choice: looser than the
    4-betting range, but far better than the whole deck, and it keeps the node
    playable when no `vs_3Bet` chart defines the 4-bet.

    Used by the reachability check and by the scenario sampler, so the validator
    and the trainer cannot disagree about what hero can be holding.
    """
    situation = meta.get("situation")
    seat = _seat(meta)
    villain = meta.get("villain_position")
    if situation == "vs_3Bet":
        return (("opens", *seat),)
    if situation == "vs_4Bet":
        return (("three_bets", *seat, villain),)
    if situation == "vs_5Bet":
        return (("four_bets", *seat, villain), ("opens", *seat))
    return ()


#: Human-readable name for each kind of prior range, for error messages.
PRIOR_RANGE_NAMES = {"opens": "opens", "three_bets": "3-bets", "four_bets": "4-bets"}


def index_prior_ranges(charts: dict[str, dict]) -> dict[tuple, tuple[str, set[str]]]:
    """Map each prior-range key to the chart that defines it and its raising hands."""
    index: dict[tuple, tuple[str, set[str]]] = {}
    for key, data in charts.items():
        meta = data.get("metadata", {})
        seat = _seat(meta)
        situation = meta.get("situation")
        if situation == "RFI":
            index[("opens", *seat)] = (key, raising_hands(data))
        elif situation == "vs_RFI":
            index[("three_bets", *seat, meta.get("villain_position"))] = (key, raising_hands(data))
        elif situation == "vs_3Bet":
            index[("four_bets", *seat, meta.get("villain_position"))] = (key, raising_hands(data))
    return index


def resolve_prior_range(
    meta: dict, index: dict[tuple, tuple[str, set[str]]]
) -> tuple[tuple, str, set[str]] | None:
    """The first prior range that is actually defined, as (key, chart key, hands)."""
    for candidate in prior_range_keys(meta):
        found = index.get(candidate)
        if found and found[1]:
            return (candidate, *found)
    return None


def validate_chart_set(charts: dict[str, dict]) -> list[ChartIssue]:
    """
    Checks that only make sense across the whole set:

    * no two charts model the same decision node
    * at nodes only reachable through hero's own raise, every hand hero
      continues with is a hand hero would actually have raised
    """
    issues: list[ChartIssue] = []
    by_node: dict[tuple, list[str]] = {}
    prior_ranges = index_prior_ranges(charts)

    for key, data in charts.items():
        node = decision_node_id(data.get("metadata", {}))
        if node is not None:
            by_node.setdefault(node, []).append(key)

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
        candidates = prior_range_keys(meta)
        if not candidates:
            continue  # hero has not acted; any hand can be here

        resolved = resolve_prior_range(meta, prior_ranges)
        if resolved is None:
            issues.append(
                ChartIssue(
                    key,
                    "no-prior-range",
                    WARNING,
                    f"no chart defines how {meta.get('hero_position')} reaches this node, so "
                    f"scenarios are dealt from the whole deck and most will be spots hero "
                    f"cannot be in",
                )
            )
            continue

        used, prior_key, prior_hands = resolved
        if used != candidates[0]:
            issues.append(
                ChartIssue(
                    key,
                    "imprecise-prior-range",
                    WARNING,
                    f"nothing defines hero's {PRIOR_RANGE_NAMES[candidates[0][0]]} range for this "
                    f"spot, falling back to {prior_key}; scenarios will include hands hero would "
                    f"not actually have here",
                )
            )

        unreachable = continuing_hands(data) - prior_hands
        if unreachable:
            issues.append(
                ChartIssue(
                    key,
                    "unreachable-continue",
                    ERROR,
                    f"continues with {_sample(unreachable)}, which {prior_key} never "
                    f"{PRIOR_RANGE_NAMES[used[0]]}",
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

"""
Invariants every strategy chart must hold.

Two groups:

* **Structural** - the chart files are well formed and internally consistent.
  These pass today and must keep passing.
* **Strategic** - the ranges themselves are sane poker. Several of these fail
  today; they are marked `xfail(strict=True)` with the phase that fixes them, so
  they turn into a failure the moment the fix lands and the marker is stale.

Reference frequencies are for 6-max, 100bb, cash, and are the bands a modern
solver-derived chart set falls into. They are deliberately wide: the point is to
catch a chart that is 10+ points off, not to pin an exact number.
"""
import json
from pathlib import Path

import pytest

from logic.chart_schema import (
    ALL_HANDS,
    DEFAULT_BASELINE,
    ERROR,
    POSITIONS,
    SITUATION_REQUIREMENTS,
    apply_baseline,
    combo_frequency,
    continuing_hands,
    decision_node_id,
    index_prior_ranges,
    load_baseline,
    load_charts,
    prior_range_keys,
    raising_hands,
    resolve_prior_range,
    validate_chart,
)

CHART_DIR = Path(__file__).resolve().parent.parent / "strategy_charts"
TOTAL_HANDS = 169


@pytest.fixture(scope="module")
def loaded():
    return load_charts(CHART_DIR)


@pytest.fixture(scope="module")
def charts(loaded):
    return loaded[0]


@pytest.fixture(scope="module")
def issues(loaded):
    return loaded[1]


def chart_files():
    return sorted(p.stem for p in CHART_DIR.glob("*.json"))


def pct(hands) -> float:
    """Combo-weighted share of the deck - the unit range frequencies are quoted in."""
    return combo_frequency(hands)


# --- Structural -------------------------------------------------------------

def test_charts_are_present():
    assert len(chart_files()) >= 43


def test_no_unexpected_validation_errors(issues):
    """The gate: any error not in CHART_KNOWN_ISSUES.json fails the build."""
    result = apply_baseline(issues, load_baseline(DEFAULT_BASELINE))
    unexpected = [i for i in result.new if i.severity == ERROR]
    assert not unexpected, "new chart validation errors:\n" + "\n".join(str(i) for i in unexpected)


def test_no_stale_baseline_entries(issues):
    """A fixed chart must be removed from the baseline, not left to rot."""
    result = apply_baseline(issues, load_baseline(DEFAULT_BASELINE))
    assert not result.stale, (
        "these baseline entries no longer occur and must be deleted from "
        "CHART_KNOWN_ISSUES.json: " + ", ".join(f"{c}:{code}" for c, code in result.stale)
    )


@pytest.mark.parametrize("chart_key", chart_files())
def test_chart_covers_every_hand_exactly_once(chart_key):
    data = json.loads((CHART_DIR / f"{chart_key}.json").read_text())
    assigned = [hand for hands in data["actions"].values() for hand in hands]
    assert len(assigned) == TOTAL_HANDS, f"{len(assigned)} assignments for {TOTAL_HANDS} hands"
    assert set(assigned) == ALL_HANDS
    assert len(set(assigned)) == len(assigned), "a hand is assigned to more than one action"


@pytest.mark.parametrize("chart_key", chart_files())
def test_chart_passes_schema(chart_key):
    data = json.loads((CHART_DIR / f"{chart_key}.json").read_text())
    found = [i for i in validate_chart(chart_key, data) if i.severity == ERROR]
    assert not found, "\n".join(str(i) for i in found)


@pytest.mark.parametrize("chart_key", chart_files())
def test_metadata_matches_filename_and_situation(chart_key):
    meta = json.loads((CHART_DIR / f"{chart_key}.json").read_text())["metadata"]
    assert meta["chart_id"] == chart_key
    assert meta["hero_position"] in POSITIONS
    for key in SITUATION_REQUIREMENTS[meta["situation"]]:
        assert meta[key] in POSITIONS
        assert meta[key] != meta["hero_position"]


@pytest.mark.parametrize("chart_key", chart_files())
def test_every_used_action_is_explained(chart_key):
    data = json.loads((CHART_DIR / f"{chart_key}.json").read_text())
    explanations = data["metadata"]["explanations"]
    for action, hands in data["actions"].items():
        if hands:
            assert action in explanations, f"{action} is used but has no explanation"
            assert explanations[action].strip(), f"{action} has an empty explanation"


def test_chart_ids_are_unique(charts):
    ids = [data["metadata"]["chart_id"] for data in charts.values()]
    assert len(ids) == len(set(ids))


# --- Strategic: opening ranges ----------------------------------------------

#: (stack depth, position, min%, max%) of the deck opened when folded to,
#: combo-weighted. Shallower stacks open tighter: the hands at the bottom of an
#: opening range are implied-odds hands, and 40bb does not pay them off.
RFI_BANDS = [
    (100, "UTG", 13.0, 19.0),
    (100, "MP", 17.0, 24.0),
    (100, "CO", 24.0, 31.0),
    (100, "BTN", 41.0, 50.0),
    (100, "SB", 38.0, 48.0),
    (40, "UTG", 12.0, 18.0),
    (40, "MP", 15.0, 22.0),
    (40, "CO", 21.0, 28.0),
    (40, "BTN", 36.0, 45.0),
    (40, "SB", 33.0, 43.0),
]


def rfi_chart(charts, position, stack=100):
    """A chart set can hold several stack depths, so the depth is part of the key."""
    for key, data in charts.items():
        meta = data["metadata"]
        if (meta["situation"] == "RFI" and meta["hero_position"] == position
                and meta["stack_depth"] == stack):
            return key, data
    raise AssertionError(f"no {stack}bb RFI chart for {position}")


@pytest.mark.parametrize("stack,position,low,high", RFI_BANDS)
def test_rfi_frequency_in_band(charts, stack, position, low, high):
    key, data = rfi_chart(charts, position, stack)
    frequency = pct(raising_hands(data))
    assert low <= frequency <= high, f"{key} opens {frequency:.1f}%, expected {low}-{high}%"


@pytest.mark.parametrize("stack", [100, 40])
def test_rfi_widens_with_position(charts, stack):
    order = ["UTG", "MP", "CO", "BTN"]
    frequencies = [pct(raising_hands(rfi_chart(charts, p, stack)[1])) for p in order]
    for earlier, later, a, b in zip(order, order[1:], frequencies, frequencies[1:], strict=False):
        assert a < b, f"{earlier} opens {a:.1f}% but {later} opens only {b:.1f}%"


# --- Strategic: blind defense -----------------------------------------------

#: (stack, hero, villain, min defend%) - BB closes the action getting a price,
#: so it defends far wider against the late positions that open widest. The
#: floors drop at 40bb: the bottom of a Big Blind defence is made of
#: implied-odds hands, which is exactly what a short stack takes away.
DEFENSE_FLOORS = [
    (100, "BB", "BTN", 50.0),
    (100, "BB", "CO", 42.0),
    (100, "BB", "MP", 36.0),
    (100, "BB", "UTG", 32.0),
    (40, "BB", "BTN", 45.0),
    (40, "BB", "CO", 34.0),
    (40, "BB", "MP", 27.0),
    (40, "BB", "UTG", 22.0),
]


@pytest.mark.parametrize("stack,hero,villain,floor", DEFENSE_FLOORS)
def test_blind_defends_wide_enough(charts, stack, hero, villain, floor):
    matches = [
        (key, data)
        for key, data in charts.items()
        if data["metadata"]["situation"] == "vs_RFI"
        and data["metadata"]["hero_position"] == hero
        and data["metadata"].get("villain_position") == villain
        and data["metadata"]["stack_depth"] == stack
    ]
    assert matches, f"no chart for {hero} facing a {villain} open"
    for key, data in matches:
        defend = pct(continuing_hands(data))
        assert defend >= floor, f"{key} defends {defend:.1f}%, expected at least {floor}%"


# --- Strategic: tree consistency --------------------------------------------

def test_each_decision_node_has_exactly_one_chart(charts):
    by_node = {}
    for key, data in charts.items():
        by_node.setdefault(decision_node_id(data["metadata"]), []).append(key)
    duplicates = {node: keys for node, keys in by_node.items() if len(keys) > 1}
    assert not duplicates, "\n".join(f"{node}: {sorted(keys)}" for node, keys in duplicates.items())


def test_continuing_ranges_are_reachable(charts):
    """
    Uses the shipped resolver rather than a local lookup.

    This test previously kept its own copy, keyed on seat alone. That was fine
    while every chart was 100bb; adding 40bb made the two opening ranges
    collide, and the narrower short-stack range shadowed the deep one. The
    production code has always keyed on stack depth too, so the fix is to stop
    reimplementing it here.
    """
    index = index_prior_ranges(charts)
    problems = []
    for key, data in sorted(charts.items()):
        meta = data["metadata"]
        if not prior_range_keys(meta):
            continue
        resolved = resolve_prior_range(meta, index)
        assert resolved, f"{key} has no chart describing how hero reaches it"
        _used, prior_key, prior_hands = resolved
        unreachable = continuing_hands(data) - prior_hands
        if unreachable:
            problems.append(f"{key} continues with {sorted(unreachable)}, not in {prior_key}")
    assert not problems, "\n".join(problems)

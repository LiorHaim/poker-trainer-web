# Strategy chart format

Every file in `strategy_charts/` describes one preflop decision node: a seat, a
situation, and an action for each of the 169 starting hands.

The format is enforced by `logic/chart_schema.py`, which runs at app startup, in
`make validate-charts`, and in CI. A chart that does not validate is a build
failure — it is not silently tolerated.

## File layout

The filename (without `.json`) is the chart key, and must equal
`metadata.chart_id`:

```
cash_6max_100bb_BTN_RFI.json   ->  chart_id "cash_6max_100bb_BTN_RFI"
```

The convention is `{game_type}_{table_size}max_{stack_depth}bb_{hero}_{situation}[_vs_{villain}]`.
Nothing parses the filename, but staying consistent keeps the directory readable.

## Document

```json
{
  "metadata": {
    "chart_id": "cash_6max_100bb_BTN_RFI",
    "description": "6-Max Cash Game, 100bb deep. Hero is on the Button and it has folded to them.",
    "game_type": "cash",
    "table_size": 6,
    "stack_depth": 100,
    "hero_position": "BTN",
    "situation": "RFI",
    "sizings": { "open_bb": 2.5 },
    "explanations": {
      "RAISE": "Why this chart raises.",
      "FOLD": "Why this chart folds."
    }
  },
  "actions": {
    "RAISE": ["AA", "KK", "AKs"],
    "FOLD":  ["72o", "32o"]
  }
}
```

### `metadata` — required keys

| Key | Type | Notes |
|---|---|---|
| `chart_id` | string | Must equal the filename stem. |
| `description` | string | Shown in Study mode. Describe the node, including the sizes it assumes. |
| `game_type` | `"cash"` \| `"mtt"` | |
| `table_size` | integer | Positive. |
| `stack_depth` | integer | Effective stack in bb. |
| `hero_position` | `UTG` \| `MP` \| `CO` \| `BTN` \| `SB` \| `BB` | |
| `situation` | see below | |
| `explanations` | object | One entry per action the chart actually uses. |

### `metadata` — situational keys

| `situation` | Meaning | Also required |
|---|---|---|
| `RFI` | Folded to hero | — |
| `vs_RFI` | Hero faces an open | `villain_position` |
| `3Bet` | Hero faces an open and may 3-bet | `villain_position` |
| `vs_3Bet` | Hero opened and faces a 3-bet | `villain_position` |
| `vs_4Bet` | Hero 3-bet and faces a 4-bet | `villain_position` |
| `squeeze` | Hero faces an open and a cold call | `opener_position`, `caller_position` |

A villain seat may not be the same as `hero_position`.

> **Known problem.** `vs_RFI` and `3Bet` describe the *same* decision — hero
> faces an open and chooses fold/call/raise — and the repo ships both for nine
> spots with conflicting answers. The validator reports this as `duplicate-node`.
> Phase 1 collapses each pair; see `CHART_KNOWN_ISSUES.json`.

### `metadata.sizings` — optional, becoming required

Bet sizes in bb that the ranges were built for: `open_bb`, `3bet_bb`, `4bet_bb`,
`5bet_bb`, `call_bb`. Currently optional and warned about, because the engine
still hardcodes 3.0bb for every open regardless of what a chart says — so a
chart built for a 2.5bb open is drilled at 3.0bb and the pot odds shown to the
user are wrong. Phase 1 makes the engine read this block and the key required.

### `actions`

An object keyed by `FOLD`, `CALL`, `RAISE`, each a list of hands in canonical
notation:

- pairs: `AA` … `22`
- suited: high rank first, `s` suffix — `AKs`, not `KAs`
- offsuit: high rank first, `o` suffix — `AKo`

All 169 hands must appear **exactly once across the whole document**. A hand
listed under two actions used to be resolved silently by dict ordering; it is
now a `duplicate-hand` error.

Every action key present must have an entry in `metadata.explanations`.

#### Formatting convention

Hands are grouped one rank family per line, strongest first. This is not
enforced, but it keeps diffs reviewable — a one-hand change should be a one-line
diff:

```json
"RAISE": [
  "AA", "KK", "QQ", "JJ",
  "AKs", "AQs", "AJs",
  "KQs", "KJs",
  "AKo"
]
```

Do not reformat a chart with `json.dump`; it flattens these groups and turns a
one-line change into a 200-line diff.

## Cross-chart rules

Checked by `validate_chart_set`:

- **`duplicate-node`** — no two charts may model the same decision.
- **`unreachable-continue`** — at a `vs_3Bet` or `vs_4Bet` node, every hand hero
  continues with must be a hand hero's own RFI chart opens. Hero cannot be
  facing a 3-bet with a hand they never raised.

## Running the validator

```bash
make validate-charts              # errors fail; known issues suppressed
python scripts/validate_charts.py -v            # list every chart behind a warning
python scripts/validate_charts.py --strict      # warnings fail too
python scripts/validate_charts.py --no-baseline # show known issues as failures
```

At runtime the same checks run when `StrategyManager` loads. Set
`CHART_VALIDATION=strict` to refuse to start when any chart fails.

## The known-issues baseline

`CHART_KNOWN_ISSUES.json` lists errors that are real, understood, and scheduled
for a later phase. They do not fail CI; anything not listed does.

The baseline is self-cleaning: if an entry stops firing — because the chart was
fixed — the validator fails with `stale baseline entries`. Fixing a chart
therefore forces its entry to be deleted in the same change.

Adding an entry requires a `reason` and a `resolved_by` phase. It is a scheduling
tool, not a way to make a problem go away.

## Resolved duplicates

Three charts shipped a hand under two actions. The loader was keeping whichever
came last in the file, so the behaviour was accidental. Resolved to match the
surrounding entries in each chart:

| Chart | Hand | Was | Now | Why |
|---|---|---|---|---|
| `CO_vs_BTN_3Bet` | `AQs` | RAISE + CALL | CALL | The RAISE list is a clean value-plus-bluff 4-bet range; AQs is a standard in-position call. Matches the loader's previous behaviour. |
| `SB_RFI` | `76s`, `75s` | RAISE + FOLD | RAISE | 65s, 64s, 54s, 53s and 43s all open; folding the two stronger hands above them was indefensible. Changes behaviour — the loader was folding them. |
| `SB_vs_CO_RFI` | `KQs`, `QJs` | RAISE + CALL | RAISE | Both sit inside a contiguous KQs/KJs/KTs/QJs/QTs/JTs raising block. Changes behaviour — the loader was calling. |

The widths these charts imply are still wrong (see `IMPROVEMENT_PLAN.md` §1.1);
that is a phase 1 retune, separate from making the files internally consistent.

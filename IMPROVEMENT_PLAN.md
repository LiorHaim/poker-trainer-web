# Poker Trainer — Full Improvement Plan

Review of [LiorHaim/poker-trainer-web](https://github.com/LiorHaim/poker-trainer-web) @ `main`, 2026-10-18.
Audited: all 52 strategy charts (programmatically), `app.py`, `logic/*`, `static/index.html`, tests, Docker/Makefile/OpenShift.
The app was run locally with a stubbed DB and driven in a browser; screenshots in `shots/`.

**Verdict:** the skeleton is good — clean chart→engine→API separation, per-user state already de-singletoned, nice
visual polish, deployment automation. The ceiling is limited by three things, in order of impact:

1. **The strategy model is binary.** One "correct" action per hand. Real preflop GTO is mixed, and the ranges
   themselves contain measurable errors and internal contradictions (evidence below).
2. **Scenarios aren't conditioned on reachability.** Hands are dealt uniformly from a 52-card deck regardless of
   whether hero could hold that hand at that node. Most reps are wasted on trivially obvious spots.
3. **The frontend is one 1301-line HTML file** with inline handlers, a CDN Tailwind build and a feedback panel
   that renders below the fold.

---

## Part 1 — Strategy: what's actually wrong

### 1.1 Measured range errors

> **Correction.** The figures below were first written as percentages of the 169
> hand *classes*, but range sizes are quoted combo-weighted — a share of the 1326
> hands you can be dealt. Offsuit hands are 12 combos and suited only 4, so the
> two differ by several points. The table is combo-weighted; it changes the
> verdict for UTG, MP and SB.

Opening frequencies, combo-weighted:

| Position | Chart | Reference (100bb 6-max) | Status |
|---|---|---|---|
| UTG | 11.2% | 15–18% | too tight |
| MP  | 16.0% | 20–23% | too tight |
| CO  | **33.3%** | 26–30% | **too wide** |
| BTN | **27.9%** | 45–50% | **far too tight** |
| SB  | 46.3% raise-only | ~40–45% pure-raise | about right, but no limp branch |

CO opens *wider than BTN* — the positional ordering is inverted at the two most important seats.
`cash_6max_100bb_BTN_RFI.json`'s own explanation text says *"we play a very wide and aggressive range (~45–50%)"*
while the chart it ships is 34.3%. The coaching text and the data disagree.

BB defense is systematically too tight — closing the action against a 2.5bb open, BB should defend far wider:

| Node | Chart defend% (combo) | Reference |
|---|---|---|
| BB vs BTN | 34.2% | 55–60% |
| BB vs CO  | 26.4% | ~45% |
| BB vs MP  | 20.1% | ~38% |
| BB vs UTG | 16.1% | ~33% |

### 1.2 Two charts give contradictory answers for the same decision node

`*_vs_*_RFI` (situation `vs_RFI`) and `*_3Bet_vs_*` (situation `3Bet`) model **the same decision** — hero faces an
open and picks fold/call/raise. Both are loaded, and `generate_scenario` picks one at random. They disagree:

```
BB_vs_BTN_RFI  vs  BB_3Bet_vs_BTN : 24/169 hands disagree  (JTs: CALL vs RAISE, T9s: CALL vs RAISE, …)
BB_vs_SB_RFI   vs  BB_3Bet_vs_SB  : 34/169 hands disagree  (99/88/77: CALL vs RAISE, …)
SB_vs_BTN_RFI  vs  SB_3Bet_vs_BTN : 29/169 hands disagree  (77–44: CALL vs FOLD, …)
SB_vs_CO_RFI   vs  SB_3Bet_vs_CO  : 11/169 hands disagree  (KTs/QTs/JTs/KQo: RAISE vs FOLD, …)
… 9 such pairs total
```

A user drilling BB vs BTN with JTs is told "CALL is correct" on one rep and "RAISE is correct" on the next.
This is the single most damaging bug in the product: it actively teaches noise.

### 1.3 Duplicate hand assignments, silently resolved by dict order

`StrategyManager._compile_chart` iterates `actions` and overwrites, so a hand listed under two actions silently
takes whichever comes last in the JSON:

```
CO_vs_BTN_3Bet.json : AQs  → ['RAISE', 'CALL']
SB_RFI.json         : 76s, 75s → ['RAISE', 'FOLD']
SB_vs_CO_RFI.json   : KQs, QJs → ['RAISE', 'CALL']
```

`SB_RFI.json` lists 171 entries for 169 hands. Nothing in the codebase catches this.

### 1.4 Scenarios are generated for nodes hero can't reach

`get_random_hand()` samples uniformly from the deck; the chart is then consulted for *all 169 hands* even at nodes
that only a subset of hands reach:

| Node | Hands that actually reach it | Fraction of random deals that are impossible |
|---|---|---|
| `UTG_vs_BTN_3Bet` | UTG's opening range | **~89%** |
| `UTG_vs_4Bet` | same | ~89% |
| `MP_vs_4Bet` | MP's opening range | ~84% |
| `CO_vs_BB_3Bet` | CO's opening range | ~67% |

So the trainer regularly presents "you opened UTG and BTN 3-bet you — you hold 72o." That node cannot exist. It is
also a free +100 bankroll, because the answer is always FOLD. `vs_4Bet` charts are 97% FOLD; drilling them as
currently generated is ~97% free points with zero learning signal.

`BTN_vs_BB_3Bet` also continues with `54s/64s/75s/86s`, four hands BTN's own RFI chart never opened — the tree is
not internally consistent.

### 1.5 Chart semantics don't match what the engine displays

`UTG_vs_4Bet.json` description: *"Hero opens UTG to 3BB, gets 3-bet, 4-bets to 25BB. Villain 5-bets all-in."*
Its explanations say *"5-bet all-in with the absolute nuts."* But `app.py:132-136` builds this node as
*villain raises to 25bb* with hero having 3-bet to 9, and the UI labels the raise button "5-Bet All-In" against a
displayed 4-bet. Three descriptions of the same node, none of them agreeing.

Same class of bug on sizings: `BB_3Bet_vs_BTN.json` says "BTN opens to 2.5BB … 3-bet to 10BB"; the engine hardcodes
3.0bb for every open and never shows the 3-bet size at all. Pot odds displayed to the user are therefore wrong
relative to the range that was built for them.

### 1.6 Missing from the decision tree

Hero 4-betting (only *facing* 4-bets exists) · vs-squeeze · limp / over-limp / iso-raise · BB vs SB limp ·
cold-calling with players left to act · blind-vs-blind as a complete subgame · any stack depth but 100bb ·
9-max · MTT / ICM (the `mtt` filter branch exists in code with zero charts behind it) · everything postflop.

### 1.7 Binary scoring is the wrong objective

`is_correct = (user_action == chart_action)` with ±100 bankroll. Problems:
- Punishes a 0.01bb mixed-strategy deviation exactly as hard as folding AA.
- At a node where the solver plays 55% raise / 45% call, one of the two is marked wrong, permanently.
- Bankroll rewards grinding trivial folds (see 1.4) over working hard spots.

---

## Part 2 — Strategy: the plan

### Phase S1 — Make the existing data trustworthy (highest value, lowest effort)

> **Status:** steps 1, 2 and 6 landed as Phase 0 (see "Progress" at the end of this
> document). Steps 3, 4 and 5 — the data changes themselves — are the remaining work.


1. **Define a chart JSON schema** and validate at load *and* in CI:
   - all 169 combos present, each exactly once;
   - every action key in the enum; every action key has an explanation;
   - `metadata.sizings` block required (`open_bb`, `3bet_bb`, `4bet_bb`, …) and used by the engine
     — no more hardcoded 3.0 in `generate_scenario`;
   - frequencies sum to 1.0 per hand (see S2).
2. **Add invariant tests** as a safety net under all future edits:
   - BTN RFI % > CO RFI % > MP > UTG; each within a published band;
   - BB defend% vs each opener inside a band derived from the pot odds it's getting;
   - every non-fold hand at a `vs_3Bet` / `vs_4Bet` node is a subset of hero's RFI range at that position;
   - no two charts model the same (hero, villain, situation) node.
3. **Collapse the duplicated node families.** Keep one chart per node (`BB_vs_BTN_open`), delete the
   `*_3Bet_vs_*` duplicates, and express "3-bet" as the RAISE branch of that one chart. This alone removes
   9 contradictory pairs and ~17% of the chart count.
4. **Fix CO/BTN/SB RFI and BB defense** to the reference bands.
5. **Fix the `vs_4Bet` naming/semantics mismatch** — pick one meaning per node id and make engine, metadata, and
   button labels agree. Generate the UI's action labels *from* the node definition, not from a JS if-chain.
6. **Record provenance.** Add `metadata.source` (solver + settings, or published chart + version) per chart.
   Without this there is no way to defend any number in the repo.

### Phase S2 — Frequency-based strategy and EV scoring

Change the chart format from `action → [hands]` to `hand → {action: frequency, …}` plus an EV per action:

```json
"JTs": { "freq": { "RAISE": 0.55, "CALL": 0.45 }, "ev": { "RAISE": 2.31, "CALL": 2.28, "FOLD": 0.0 } }
```

Then:
- **Score by EV loss**, not by equality. `ev_loss = max(ev) - ev[user_action]`, reported in bb/100.
  A pure blunder costs real bb; a mixed-strategy edge case costs ~0.
- Accept *any* action the solver plays at ≥ some threshold as "fine", and show the mix.
- Replace the bankroll with **bb/100 won vs. the solver** — the metric players actually care about, and one
  that cannot be farmed by folding 72o.
- Render mixed cells in the matrix as split/gradient rather than a single colour.

This is the single biggest strategic upgrade; everything else in the product gets better once the scoring
function is correct. The chart format change is mechanical (a converter script keeps existing pure charts valid
as `freq: {X: 1.0}`).

### Phase S3 — Scenario sampling that teaches

1. **Condition the deal on node reachability.** Sample hero's hand from the range that arrives at the node
   (hero's RFI range for `vs_3Bet`, hero's 3-bet range for `vs_4Bet`, …), weighted by combo count.
   Kills the 84%-impossible-scenario problem.
2. **Weight toward the decision boundary.** Rank hands at each node by `|ev_best − ev_second|`; sample with a
   bias toward small gaps (the hands that are actually hard). Keep a configurable share of easy hands so the
   drill still feels like poker.
3. **Spaced repetition on the user's own leaks.** Track per (node, hand-class) EV loss; resurface items the user
   has failed, with an SM-2-ish interval. This is what turns the app from a quiz into a trainer.
4. **Node sampling proportional to real-world frequency** (RFI spots happen far more often than vs-4-bet),
   with an override for Focus mode.

### Phase S4 — Breadth

Priority order by learning value per chart authored:
1. Sizing-aware action space: open 2.2x/2.5x/3x, 3-bet IP vs OOP sizes, 4-bet small vs jam, all-in.
2. Hero 4-bet and vs-squeeze nodes (completes the preflop tree).
3. Blind-vs-blind including limps.
4. Stack depths 40 / 60 / 200bb (`by_stack` stats already exist and are currently always "100").
5. 9-max, then MTT with ICM pressure.
6. Postflop phase: single-raised-pot c-bet / check-raise drilling on clustered flop textures. Separate product
   surface — don't start until preflop is correct.

---

## Part 3 — Code and architecture

### 3.1 Correctness / reliability bugs

| Issue | Where | Impact |
|---|---|---|
| `_user_state` is per-process | `app.py:85` | With >1 gunicorn worker, `/api/start` on worker A then `/api/act` on worker B returns "No active scenario." The app is currently only correct at 1 worker. |
| `_user_state` never evicted (except explicit logout) | `app.py:85` | Unbounded memory growth. |
| `_rate_limits` keyed by IP, never pruned | `app.py:49` | Unbounded memory growth; also per-process, so N workers = N× the limit. |
| Rate limiter counts successful logins | `app.py:51` | Legit users get 429s. |
| Bankroll recomputed by full-history aggregation on every action | `statistics_db.py:83` | O(history) per hand. Replace with an incrementing counter doc. |
| Bankroll constants duplicated 3× | `app.py:43-45`, `statistics_db.py:97-99`, aggregation pipeline `:119` | Change one, the leaderboard silently disagrees with the HUD. |
| `logic/trainer.py` is dead code | whole file | A stale duplicate of the `app.py` helpers, with its own drift. Delete. |
| `/api/charts`, `/api/chart/<key>` unauthenticated | `app.py:240-258` | All content is public. Fine if intentional — decide explicitly. |
| No CSRF token on cookie-auth POSTs | all POST routes | `SameSite=Lax` covers most of it; add a token if this ever goes multi-origin. |
| Hand not found in chart → silent FOLD | `strategy.py:84` | Masks exactly the data gaps Part 1 is about. Should raise in CI, warn loudly at runtime. |

**Recommended fix for the state problem:** make `/api/act` stateless. Return the scenario to the client with an
HMAC-signed token encoding `(chart_key, hand, nonce, issued_at)`; `/api/act` verifies the signature instead of
looking up server state. Removes `_user_state` entirely, makes the app horizontally scalable, and closes the
"replay the same scenario" hole. Redis is the alternative but this is simpler and has no new dependency.

### 3.2 Structure

- Promote `logic/` to a real domain package: `ranges/` (Range type, combo math, frequency ops), `tree/`
  (node definitions, sizings, reachability), `scoring/` (EV loss, streaks, spaced repetition), `charts/`
  (loader + schema). Node definitions become **data**, not an if/elif chain duplicated in `app.py`,
  `trainer.py`, and `renderScenario()` in JS.
- Pydantic models for chart JSON and API payloads; typed responses shared with the frontend.
- Split `app.py` into Flask blueprints (`auth`, `game`, `stats`, `charts`), app factory, config object.
- Persistence: keep Mongo if you like it, but store (a) an append-only decision event collection and
  (b) a per-user rollup document updated on write. Current reads re-derive everything from raw events.

### 3.3 Testing & CI

Current state: two unittest files, ~110 lines, covering hand notation. `make test` runs one file directly.
The bugs in Part 1 are all mechanically detectable.

- Move to pytest; `make test` runs the whole suite.
- Chart invariant tests (Phase S1.2) — this is where the ROI is.
- API contract tests with a mongomock / test-container backend.
- Property tests: every hand at every node resolves to a defined action; EV tables are internally consistent.
- Playwright smoke test: login → drill → answer → feedback visible without scrolling.
- GitHub Actions: lint (ruff) + types (mypy) + tests + chart validation on every PR. There is no CI today.

### 3.4 Packaging / deploy

- Dockerfile runs as root, installs on top of a floating `python:3.11-slim`, no `HEALTHCHECK`, no layer caching
  for app code. Add a non-root user, pin the base by digest, add `HEALTHCHECK` against `/api/health`.
- `/api/health` returns 200 while `strategy_mgr` is `None`-checked but the app still serves 500s — make it a
  real readiness probe and wire it into `openshift.yaml`.
- Pin dependencies with a lockfile (`uv` or `pip-tools`).

---

## Part 4 — Appearance and UX

Observed live (see `shots/02-train.png`, `shots/03-feedback.png`).

### 4.1 The flow problems

1. **Feedback renders below the fold.** After answering, the result panel and range matrix appear ~1050px down
   a 900px viewport — the user must scroll on every single hand. This is the worst UX bug in the app; a drill
   loop must be zero-scroll and zero-mouse.
2. **Dead vertical space.** Content is capped at `max-w-3xl` on a 1280px screen, with ~250px of empty gap
   between the table and the cards. Go two-column on desktop: table + cards + actions left, feedback + matrix
   right, both always visible.
3. **Hero isn't seated at the bottom.** Seats are hard-pinned to absolute positions (`.seat-BTN { right: -15px }`),
   so hero appears wherever their position is. Every real client rotates hero to bottom-centre; reading
   position becomes instant instead of a lookup.
4. **The table shows no money.** No stacks at seats, no bet chips, no pot chips in the middle. "MP opens 3bb"
   exists only as HUD text. Rendering the actual chips is how players read a spot at a glance.
5. **Cards float detached** from the table, below it, separated by a stray blurred divider
   (`index.html:574`) that reads as a rendering artifact.
6. **Visible glitches:** the empty `#toast` renders as a dark pill over the keyboard-hint row and over the
   Call button; the dealer "D" badge overlaps the BTN seat circle.

### 4.2 Design system

- Four competing accent families (emerald / amber / red / blue / teal / yellow / violet). Pick 1 brand accent +
  semantic colours and define tokens. Currently colours are inline Tailwind utilities repeated dozens of times.
- **Red/green is the matrix palette and also the fold/raise button palette.** ~8% of men are red-green
  colour-blind; for them the range matrix is unreadable. Move to a colour-blind-safe scheme
  (e.g. blue→raise, amber→call, grey→fold) with a pattern/texture fallback, and keep button colour consistent
  with matrix colour so the mapping is learnable.
- `cdn.tailwindcss.com` in production (the console warns about it on every load): ~300KB of JIT compiler
  shipped to the client. Build Tailwind properly.
- Self-host the three Google fonts; drop the render-blocking external requests.
- `preload="auto"` on six WAVs plus a ~14-track MP3 playlist — lazy-load audio on first interaction.

### 4.3 Frontend architecture

One 1301-line `index.html`: global mutable state, `onclick="..."` attributes, `innerHTML` string templates
rebuilt per hand, no modules, no build, no tests. Options:

- **Minimal:** split into `index.html` + `src/*.js` ES modules + a Vite build; keep vanilla. Low risk, keeps
  the aesthetic, fixes the build and testability problems. Recommended if you want to stay lightweight.
- **Fuller:** React/Svelte + TypeScript with generated API types. Worth it once mixed-frequency matrices,
  a sizing-aware action bar, EV meters and a leak dashboard all need to coexist.

Either way: a small state machine for the drill loop (`idle → dealt → answered → revealed`), components for
`Table`, `SeatStack`, `RangeMatrix`, `FeedbackPanel`, and one source of truth for node labels (from the server,
not the JS if-chain at `index.html:962-1012`).

### 4.4 Trainer-specific UI features worth adding

- **EV-loss meter** per decision instead of Correct/Incorrect, plus a running bb/100.
- **Mixed-strategy display:** show the solver's mix ("55% raise / 45% call — your call is fine, −0.03bb").
- **Leak dashboard:** worst nodes by EV loss, worst hand classes, trend over time. Current stats are
  accuracy-by-position and accuracy-by-stack (and stack is always 100).
- **Range matrix always on screen**, dimmed before the answer, revealed after — rather than appearing from
  nowhere post-answer.
- **Keyboard-only loop** (already half-built: F/C/R/Space). Add sizing keys once the action space grows.
- **Session goals** ("50 hands of BTN vs 3-bet") and a timed mode for decision speed.
- **Explanations tied to the specific hand**, not one canned paragraph per action per chart. Even a templated
  line referencing blockers / pot odds / position beats the current static text.

---

## Part 5 — Suggested sequencing

| Phase | Work | Why first |
|---|---|---|
| **0** | Chart schema + invariant tests + CI | Nothing else is safe to build on. Catches §1.1–1.4 automatically. |
| **1** | Collapse duplicate node families; fix CO/BTN/SB RFI and BB defense; fix `vs_4Bet` semantics; delete `trainer.py` | Stops the app teaching contradictions. Small diff, big correctness win. |
| **2** | Reachability-conditioned sampling | Removes ~60–84% wasted reps at the deep nodes. Pure engine change, no new data. |
| **3** | Frequency + EV chart format, EV-loss scoring, bb/100 | The core strategic upgrade. Requires re-sourcing the chart data — the big data task. |
| **4** | Stateless signed-scenario tokens; blueprints; rollup stats; non-root Docker | Makes the backend scalable and maintainable; do alongside 3. |
| **5** | Frontend rebuild: zero-scroll two-column drill loop, hero-at-bottom table with chips, mixed-strategy matrix, colour-blind-safe palette, real Tailwind build | Needs the EV/frequency API from phase 3 to be worth doing once. |
| **6** | Breadth: sizings, 4-bet/vs-squeeze nodes, stack depths, spaced repetition, leak dashboard | Growth work on a correct base. |
| **7** | Postflop trainer | New product surface. |

---

---

## Progress

### Phase 0 — done

Everything in Part 1 is now detected automatically; nothing in Part 1 can regress unnoticed.

- **`logic/chart_schema.py`** — the single definition of a valid chart. Per-chart structure, metadata,
  hand notation, full 169-hand coverage, duplicate assignments; cross-chart duplicate decision nodes and
  unreachable continuing ranges.
- **`StrategyManager` loads through it.** Problems are logged rather than silently absorbed —
  `_compile_chart` no longer resolves a double-assigned hand by dict ordering, and a missing hand logs an
  error instead of quietly teaching a fold. `CHART_VALIDATION=strict` refuses to start on any error.
- **`scripts/validate_charts.py`** + `make validate-charts`, `make lint`, `make check`.
- **`CHART_KNOWN_ISSUES.json`** — the 19 outstanding errors (18 `duplicate-node`, 1 `unreachable-continue`),
  each with a reason and the phase that fixes it. CI fails on anything new, *and* on a baseline entry that
  stops firing — so fixing a chart forces its entry to be deleted in the same change.
- **`tests/test_chart_invariants.py`** (data) and **`tests/test_chart_schema.py`** (the validator itself,
  fed deliberately broken charts so the gate is not vacuous). 260 passing, 10 `xfail(strict=True)` marking
  the §1.1/§1.2/§1.4 range problems — each becomes a build failure the moment it is fixed.
- **Three charts de-duplicated** — `CO_vs_BTN_3Bet` AQs, `SB_RFI` 76s/75s, `SB_vs_CO_RFI` KQs/QJs.
  Resolutions and their rationale are in `docs/CHART_SCHEMA.md`.
- **pytest, ruff, GitHub Actions** on 3.11 and 3.12. The repo had no CI; `make test` ran a single file.
- **`docs/CHART_SCHEMA.md`** and README updated.

Deliberately *not* done in Phase 0, to keep the data changes separate from the tooling that checks them:
collapsing the duplicate node families, retuning CO/BTN/SB opens and blind defense, the `vs_4Bet` semantics
fix, and deleting `logic/trainer.py` (`tests/test_integration.py` currently only exercises that dead module —
worth rewriting against the real `app.py` path when it goes).

### Phase 1 — done

**Chart data (§1.1–1.5).**

- The `3Bet` situation is gone. `vs_RFI` covers facing an open, raise branch included; the nine duplicate
  `*_3Bet_vs_*` charts are deleted and the schema rejects the situation outright. 52 charts → 43.
- All 14 opening and blind-defense charts regenerated from range specs in `chart_sources/` via
  `scripts/author_chart.py`, with the spec recorded in `metadata.source`. Every frequency is now inside the
  reference bands and monotonic by position; `CHART_KNOWN_ISSUES.json` is empty and every `xfail` is gone.
- Five `vs_4Bet` charts were actually describing a 5-bet spot — position order makes the other reading
  impossible, and their own explanations said "5-bet all-in". Split into a new `vs_5Bet` situation and
  renamed; `BTN_vs_MP_4Bet` is the one genuine `vs_4Bet` node.
- `metadata.sizings` is required on every chart, and `metadata.source` records provenance. The authored
  ranges are marked `"type": "authored"` — reasonable reference ranges, not solver output.

**Engine (§1.5, §3.1, §3.2).**

- `logic/nodes.py` is the single definition of what a situation means: who acted, for how much, what is in
  the pot, what hero must call. This replaces an if/elif chain duplicated across `app.py`, `trainer.py` and
  a JavaScript function, plus the hardcoded pot table in `TrainingScenario` that disagreed with all of them.
  The dead-code comments in `scenario.py` ("This is getting complex. Let's hardcode") are gone with it.
- Pot and to-call are computed from each chart's declared sizings, so a chart built for a 2.5bb open is
  drilled at 2.5bb. Blinds posted by hero or the villain are no longer double-counted.
- The raise button's label and the action description come from the server, so the UI no longer keeps its
  own copy of what each situation means. `/api/charts` returns `situation`, replacing the substring matching
  the study view used to guess it with.
- `logic/trainer.py` deleted. `tests/test_integration.py` only ever exercised that dead module; it now
  drives `app.py` through a Flask test client, with the database faked.

Still open from Part 1: §1.6 (missing nodes — hero 4-betting, vs-squeeze, limps, other stack depths) and
§1.7 (binary scoring), which are phases 3 and 4.

### Appendix — audit scripts

The throwaway scripts used to produce the tables in Part 1 are now superseded by
`tests/test_chart_invariants.py` and `scripts/validate_charts.py`.

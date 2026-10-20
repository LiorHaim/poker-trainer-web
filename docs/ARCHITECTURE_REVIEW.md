# Architecture review

> **Status: F1, F2, F3, F5 and F10 are fixed** (commit `4480b46`) and verified
> against the live cluster — see "Verification results" at the end. F4 (MongoDB
> has no authentication) is the remaining High and is deliberately untouched,
> because enabling auth on a database with data in it can take the app offline
> and wants its own change. F6–F9 and F11 remain open.

Reviewed at `2ebcdf6`, 2026-10-20. Scope: the whole system — domain, web layer,
persistence, deployment. Findings are ordered by what would hurt first, not by
how interesting they are.

Disclosure: I wrote most of the current architecture over phases 0–6, so this is
a self-review. I have tried to be harder on the recent work than on the
inherited code, because the recent work has had less time to be found wrong.

---

## 1. Context

```
                   ┌──────────────────────────────────────┐
  browser ──TLS──▶ │ OpenShift route (edge termination)    │
                   └───────────────┬──────────────────────┘
                                   │
                   ┌───────────────▼──────────────────────┐
                   │ poker-trainer  ×2 replicas            │
                   │   gunicorn ×2 workers each (4 procs)  │
                   │   Flask, single module app.py         │
                   │   charts loaded in-process at import  │
                   └───────────────┬──────────────────────┘
                                   │ unauthenticated
                   ┌───────────────▼──────────────────────┐
                   │ mongodb ×1, RWO PVC 1Gi, no auth      │
                   │   users · history · totals · reviews  │
                   └──────────────────────────────────────┘
```

Training state is **not** server-side: it travels in an HMAC-signed token held
by the client, which is what allows more than one replica. Strategy charts are
read-only data loaded into each process at import.

**Quality attributes that actually matter here**, in order: correctness of the
strategy data (it is a teaching tool — wrong data is worse than downtime),
maintainability (one author, long-lived side project), then availability. It is
a single-digit-user training app, not a system that needs five nines. Several
findings below are deliberately *not* recommended for fixing on those grounds.

### What is working

- **`logic/` is genuinely clean.** No Flask, no pymongo outside
  `statistics_db.py`. `chart_schema`, `nodes`, `review`, `range_spec` are
  dependency-free domain code, which is why they are cheap to test.
- **The chart pipeline is the strongest part of the system.** A schema, a
  validator shared by the loader/CI/tests, a known-issues baseline that fails
  when it goes stale, and invariants asserted as tests. Data bugs cannot
  silently return.
- **One definition of reachability** (`chart_schema.prior_range_keys`) used by
  both the validator and the sampler. The trainer and the checker cannot drift.
- **The token design** removed shared mutable state cleanly and was verified
  cross-pod on a real cluster.

---

## 2. Findings

### F1 — The health endpoint reports connectivity it never checks · **High**

`app.py:215-217`

```python
"db_connected": stats_mgr is not None,
status_code = 200 if strategy_mgr and stats_mgr else 503
```

This is an object-reference check, not a connectivity check. I initially assumed
it was at least correct at startup — that a dead Mongo would make the
constructor raise, leaving `stats_mgr` as `None`. **It does not.**
`MongoClient()` connects lazily, `get_database()` issues no command, and
`_create_indexes()` — the only call that would touch the server — swallows its
own failure with `logger.warning` (`statistics_db.py:56-57`). So
`StatisticsManagerDB.__init__` returns successfully against a database that does
not exist. Verified:

```
$ StatisticsManagerDB('mongodb://127.0.0.1:59999/poker')   # nothing listening
  __init__ SUCCEEDED -> stats_mgr is not None
  /api/health reports: db_connected=true, HTTP 200
```

There is therefore **no state in which this probe reports a database problem**.
A pod with no database at all comes up, passes readiness, receives traffic, and
500s on the first request that touches Mongo. The field is worse than absent: it
is a confident false signal during the exact incident you would use it to
diagnose.

### F2 — Liveness and readiness are the same endpoint · **High**

`openshift.yaml:130-143` — both probes hit `/api/health`.

These must answer different questions. Liveness is "is this process wedged,
restart it"; readiness is "can this process serve right now". Pointing both at a
dependency-aware endpoint means a Mongo blip restarts every app pod
simultaneously — turning a recoverable dependency outage into a
self-inflicted cascading restart.

**Note how F1 and F2 currently mask each other.** The probes are survivable
today only because the health check does not really test Mongo. Fix F1 on its
own — make `/api/health` honest — and you immediately *create* the cascading
restart described here, because liveness now fails whenever Mongo does. They
have to be fixed together: a dependency-free `/api/health/live`, and a
`/api/health/ready` that pings Mongo (`client.admin.command('ping')`) with a
short timeout, wired to the matching probes.

This is the one pair in this review where doing half the work is worse than
doing none of it.

### F3 — The Mongo deployment will deadlock on its first update · **High (latent)**

`openshift.yaml` — the `mongodb` Deployment declares no `strategy`, so it
defaults to `RollingUpdate`, while `mongo-pvc` is `ReadWriteOnce`. On any change
to the Mongo pod spec, Kubernetes starts a second pod before terminating the
first; that pod cannot attach a volume the old one still holds, and the rollout
hangs with the new pod `Pending` on a multi-attach error.

It has not fired because nobody has edited the Mongo spec since creation. It
will fire the first time someone bumps the image. One line: `strategy: {type: Recreate}`.

### F4 — MongoDB has no authentication and nothing restricts access to it · **High**

The connection string is `mongodb://mongodb:27017/poker` — no credentials — and
there are no NetworkPolicies in the namespace. Any pod that lands in this
namespace can read and write every account record, including password hashes,
and the whole decision history.

The hashes are scrypt via Werkzeug, so this is not instant credential loss, but
"database with no auth" is not a posture to leave in place once the app is on a
public route. Enable auth, put the credentials in the existing Secret, and add a
default-deny NetworkPolicy admitting only the app's pod selector.

### F5 — The persistence layer swallows every failure · **High for a system of record**

17 `except Exception` blocks in `logic/statistics_db.py`, each logging and
returning a neutral default. The consequences differ sharply by method:

| Method | On failure | Consequence |
|---|---|---|
| `log_decision` | logs, returns | The hand is silently not recorded. Deliberate — losing a hand beats breaking the drill. Fine. |
| `get_bankroll` | returns `STARTING_BANKROLL` | **A Mongo outage shows every user exactly $10,000.** Indistinguishable from a new account. |
| `get_leaderboard` | returns `[]` | Renders as "no players yet". |
| `get_due_reviews` | returns `[]` | Adaptive drilling silently degrades to random. |

Blanket catch-and-default is the right call for the write path and the wrong
call for reads, where it manufactures plausible-looking wrong answers. Reads
should propagate and let the route decide; the UI can then say "stats
unavailable" instead of quietly lying about your bankroll.

### F6 — `StatisticsManagerDB` is four components in one class · **Medium**

359 lines covering: credential store (`create_user`, `verify_user`), append-only
event log (`log_decision`, `get_recent_history`), scoring (`bankroll_from`,
`get_leaderboard`), and the spaced-repetition scheduler (`_reschedule`,
`get_due_reviews`). Those have different reasons to change and different
consistency needs.

The scheduler is the clearest violation: `_reschedule` makes a domain decision —
when a spot should next appear — inside a Mongo adapter. `logic/review.py` holds
the pure policy, but the orchestration that calls it lives in persistence, so it
can only be tested through a database.

There is also no port. `app.py` depends on the concrete class, and the one place
that needed a seam (tests) got a hand-written fake that drifted out of step and
broke. Swapping that fake for mongomock was the right short-term fix; the
structural fix is an interface the domain owns.

### F7 — `app.py` is the whole web tier in one module · **Medium**

576 lines: bootstrap, config, security headers, rate limiting, auth routes, game
routes, stats routes, serialization, and a response cache. Module-level
`strategy_mgr` / `stats_mgr` globals, assigned in a `try/except` at import, mean:

- handlers are untestable without monkeypatching module attributes;
- there is no app factory, so you cannot build a second instance with different
  config in-process;
- a startup failure leaves the module importable with `None` managers, so the
  process *runs* while serving 503s rather than exiting non-zero and letting the
  platform back off visibly.

Blueprints plus an app factory and explicit dependency wiring is the
conventional fix. I have twice deferred this as "churn with no behaviour
change", which was right both times — but it is now the thing making every other
web-layer change more expensive, and should ride along with the next feature
that touches routing.

### F8 — The bankroll is defined twice, over two different sources · **Medium**

`bankroll_from()` computes it in Python from the `totals` document.
`get_leaderboard` recomputes the same formula as a hand-written Mongo
aggregation over `history`. Phase 4 consolidated the *constants* but not the
*formula*, and the two read different collections.

They agree only because of the lazy backfill. Any future change to scoring — and
phase 3's EV-loss scoring is exactly that — has to land in both, in two
languages. The leaderboard should read `totals` and share the one formula.

### F9 — Per-process state that two replicas made wrong · **Medium**

Both were correct at one replica and became incorrect when I set `replicas: 2`:

- `_rate_limits` (`app.py:53`) — per process, so 4 gunicorn workers allow 4× the
  intended login attempts. Documented in a comment, but the comment does not
  make the limit effective.
- `_leaderboard_cache` (`app.py:355`) — per process with a 60s TTL, so two users
  can see different leaderboards, and the same user can see it flip between
  refreshes depending on which pod answers.

Neither warrants Redis at this scale. The honest options are to shorten the
leaderboard TTL and accept the skew, or move both to Mongo (a TTL collection
costs one round trip and removes the whole class of problem).

### F10 — Client settings are unvalidated, then signed and replayed · **Medium**

`_normalised_settings` (`app.py`) fills defaults but validates nothing.
`filter_scenarios` then does `int(settings.get("table_size", 6))` on whatever the
client sent. `{"table_size": "abc"}` raises `ValueError`, caught by the route's
blanket handler, returning 500.

The part that makes this structural rather than cosmetic: those settings are
**signed into the training token** and replayed on every subsequent
`/api/next`. One malformed value poisons the session until the user starts over.
Validate at the trust boundary — before signing — and reject with a 400.

### F11 — No API versioning or shared contract · **Low now, compounding**

Routes are unversioned `/api/*`, and the contract exists only as whatever
`serialize_scenario` emits and what 1433 lines of `static/index.html` happen to
read. Phase 1 already shipped a breaking change (`/api/next` GET→POST) that
worked only because the client is deployed in the same image.

That coupling is load-bearing and currently free. It stops being free the moment
anything else consumes the API.

### F12 — Accepted risks, restated

- ~~**Token replay**~~ — **fixed.** This was not theoretical: the action buttons
  stayed live after the result was shown, so clicking again answered the same
  hand, and one deal could be cycled through all three actions until one was
  right. Measured before the fix: one dealt hand produced five logged decisions.
  Tokens now carry a nonce claimed on first answer, in a Mongo collection that
  expires itself; a repeat returns 409.
- **No CSRF token** — `SameSite=Lax` covers the realistic cases for a
  same-origin cookie app; revisit if a second origin appears.
- **Charts served unauthenticated** — fine if the content is not the product.

---

## 3. Recommendations

Sequenced by value over cost, not by severity.

| # | Action | Cost | Addresses |
|---|---|---|---|
| 1 | Split probes: dependency-free `/health/live`, Mongo-pinging `/health/ready`; point the manifest at each. **Must be done as one change** | ~1h | F1, F2 |
| 2 | `strategy: {type: Recreate}` on the Mongo Deployment | 1 line | F3 |
| 3 | Mongo auth via the existing Secret + default-deny NetworkPolicy | ~2h | F4 |
| 4 | Let read-path failures propagate; keep catch-and-continue only on `log_decision` | ~2h | F5 |
| 5 | Validate settings before signing them into a token | ~1h | F10 |
| 6 | Leaderboard reads `totals` and shares `bankroll_from` | ~1h | F8 |
| 7 | Extract a `StatsRepository` port; move scheduler orchestration into the domain | ~1d | F6 |
| 8 | App factory + blueprints + explicit wiring | ~1d | F7 |
| 9 | Decide on `_rate_limits` / `_leaderboard_cache`: Mongo-backed or documented-and-accepted | ~0.5d | F9 |

Items 1–6 are a single afternoon and remove every High. Items 7–8 are the
structural debt; they are best done as preparation for phase 3, which will touch
both the scoring path and the API contract anyway.

### Explicitly not recommended

- **Microservices / event sourcing / CQRS.** This is one bounded context with
  one writer and ~1k documents. Splitting it would add network failure modes to
  buy nothing.
- **Redis.** Two caches that do not need to be correct is not a reason to run
  another stateful service; Mongo is already there.
- **Replacing Mongo with Postgres.** The data is relational and the aggregations
  would be nicer in SQL, but the schema is small, the queries work, and a
  migration spends a day to make nothing observably better.

---

## 4. Validation plan

Nothing above should land without a way to see that it worked.

- **F1/F2** — scale Mongo to zero, confirm readiness flips to 503 while liveness
  stays 200 and **no app pod restarts**; scale back and confirm recovery with no
  intervention. Add a unit test that constructs the manager against a dead port
  and asserts readiness reports unhealthy — that is the case that is wrong today
  and the one a future refactor is most likely to reintroduce.
- **F3** — `oc set env deploy/mongodb FOO=bar` on a throwaway namespace and watch
  the rollout complete rather than hang.
- **F4** — confirm the app still connects with credentials, then exec into an
  unrelated pod and confirm the connection is refused.
- **F5** — point the app at a dead Mongo and confirm the UI reports stats as
  unavailable rather than showing $10,000.
- **F8** — assert in a test that `get_leaderboard` and `get_bankroll` return the
  same figure for the same user.

## 5. Assumptions

- Single-digit concurrent users; no growth forecast was given. If that is wrong —
  particularly if this becomes multi-tenant or publicly promoted — F4, F9 and
  F12's replay risk all move up sharply.
- The OpenShift workshop cluster is ephemeral and the deployment is a demo.
  Durability of the Mongo PVC is assumed not to matter; if it does, there is no
  backup of any kind, which would be a finding in its own right.
- Strategy charts stay read-only data loaded at import. If they become
  user-editable, the in-process cache across 4 workers becomes a coherence
  problem.


---

## 6. Verification results (2026-10-20)

Run against the live OpenShift deployment, two replicas.

### Before

MongoDB scaled to zero:

```
/api/health   200  {"db_connected": true, "status": "healthy"}
pods          both Ready, 0 restarts, route still routing
register      {"error": "Username already taken"}
login         {"error": "Invalid credentials"}
leaderboard   []   (renders as "No players yet")
```

Worse than F1 predicted. The health check could not detect a missing database
*at any point*, not merely after startup: `MongoClient` connects lazily and
`_create_indexes` swallowed its own failure, so the manager constructed happily
against a dead port. And the defaults did not merely hide the outage, they
produced confident falsehoods — a user with the correct password was told it
was wrong.

### After

Same outage, same cluster:

```
/api/health/live    200  {"status": "alive"}          <- no restarts
/api/health/ready   503  {"db_connected": false}
pods                both NotReady
service endpoints   0                                  <- pulled from the LB
restarts            0
register / login    503  "Service temporarily unavailable - cannot reach the account store."
leaderboard         503  "Service temporarily unavailable - cannot read the leaderboard."
```

Recovery after scaling MongoDB back up: readiness returned within ~6s with no
intervention, zero restarts across the whole incident, 6 users and 142 hands
intact.

### F3

`strategy: Recreate` applied, then a Mongo pod-spec change forced
(`oc set env deploy/mongodb ROLLOUT_TEST=1`) — the exact operation that would
previously have hung forever on a multi-attach error against the ReadWriteOnce
volume:

```
deployment "mongodb" successfully rolled out
```

### F4 — demonstrated, not fixed

A throwaway pod with no credentials, scheduled into the namespace:

```
connected with NO credentials from an unrelated pod
collections: history, reviews, totals, users
user accounts readable: 6
password hashes exposed: yes
decision history rows: 142
```

This is the remaining High. It needs MongoDB auth plus a default-deny
NetworkPolicy, applied in that order, with a rollback plan — a mislabelled
selector takes the app offline instantly.

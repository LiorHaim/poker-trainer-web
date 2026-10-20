# Poker Trainer Web

A web-based Texas Hold'em preflop trainer that helps you drill GTO-based preflop decisions, get instant feedback, and track your accuracy over time.

Built with Flask, MongoDB, and a lo-fi themed frontend.

## Features

- **45 Strategy Charts** — covers all key 6-Max 100BB spots: RFI, vs RFI (including 3-betting), vs 3-Bet, vs 4-Bet, vs 5-Bet, and Squeeze
- **Drill Mode** — continuous hands across all loaded charts, dealt only from ranges that can actually reach each spot
- **Adaptive Review** — spots you get wrong come back on a spaced-repetition schedule and stop appearing once you have them down
- **Focus Mode** — practice a specific position or situation (e.g. "only BTN spots")
- **Instant Feedback** — see whether your action matches the reference strategy, with a coaching explanation, without leaving the spot on screen
- **Close Decisions** — hands the chart plays two ways are accepted either way and shown as a split cell, instead of marking a legitimate line wrong
- **Visual Range Matrix** — the full chart sits beside the table the whole time, masked until you act, with your hand highlighted
- **Leak Report** — overall accuracy, your weakest decision nodes, and the hand classes you misplay most
- **Leaderboard** — compete with other users
- **Lo-fi Music Player** — ambient background music while you train
- **User Accounts** — register/login to persist stats across sessions

## Strategy Charts Included

All charts are for **Cash Game, 6-Max, 100BB effective stacks**:

| Spot | Charts |
|------|--------|
| RFI (open raise) | UTG, MP, CO, BTN, SB |
| vs RFI (facing open) | BB vs all positions, SB vs BTN/CO/MP/UTG, BTN vs UTG/MP/CO, CO vs UTG/MP |
| vs 3-Bet | UTG/MP/CO/BTN/SB vs various 3-bettors |
| vs 4-Bet | BTN, having 3-bet an MP open |
| vs 5-Bet | UTG/MP/CO/BTN/SB, having opened and 4-bet |
| Squeeze | SB & BB squeeze vs opener+caller combos |

Facing an open is a single chart per spot whose RAISE branch is the 3-bet.
There used to be a second `3Bet` chart family describing the same decision with
conflicting answers; it was removed.

Opening and blind-defense ranges are generated from the range specs in
[`chart_sources/`](chart_sources/) — see "Authoring a chart" in the schema docs.
They are hand-authored reference ranges, recorded as `metadata.source.type:
"authored"`, not solver output.

Chart files are validated against a schema at startup and in CI — see
[`docs/CHART_SCHEMA.md`](docs/CHART_SCHEMA.md) for the format and
[`CHART_KNOWN_ISSUES.json`](CHART_KNOWN_ISSUES.json) for the strategy problems
currently being worked through.

## Project Status

An audit of the chart data and the app is written up in
[`IMPROVEMENT_PLAN.md`](IMPROVEMENT_PLAN.md), with a phased plan to work through
it. Progress:

| Phase | Work | Status |
|---|---|---|
| 0 | Chart schema, validation, invariant tests, CI | done |
| 1 | Collapse duplicate decision nodes; retune opening and blind-defense ranges | done |
| 1b | Wire per-chart sizings; fix vs-4-bet semantics; delete dead `logic/trainer.py` | done |
| 2 | Deal hands only from ranges that can reach the node | done |
| 3a | Close decisions: accept either action where the chart draws a hard line | done |
| 3b | Real mixing frequencies and EV-loss scoring | needs solver exports |
| 4 | Stateless scenario tokens, rollup stats, container hardening | done |
| 5 | Zero-scroll drill loop, hero-at-bottom table, colour-blind-safe palette | done |
| 6 | Spaced repetition and leak reporting | done |
| 7 | Breadth: more stack depths, vs-squeeze, limps, 9-max, MTT | planned |

Range frequencies are asserted against reference bands in
`tests/test_chart_invariants.py`, so a chart cannot drift back out of range
unnoticed. Strategic gaps still outstanding are tracked there as `xfail` tests,
which turn into build failures the moment they are fixed and the marker is
stale.

## How a training session works

The server keeps nothing between requests. `/api/start` returns the first hand
plus a signed token describing the session's filters and the live hand;
`/api/act` and `/api/next` send that token back. This replaced a per-process
dict that made the app correct only at a single worker — a hand started on one
worker could not be answered on another — and that grew without bound.

A token is bound to the account it was issued to, expires after 12 hours, and
carries a nonce so a dealt hand can be answered exactly once — a repeat answer
is rejected with 409.

## Tech Stack

- **Backend:** Python, Flask, Gunicorn
- **Database:** MongoDB (via PyMongo)
- **Frontend:** Vanilla HTML/CSS/JS (single-page app)
- **Deployment:** Docker, OpenShift

## Quick Start

### Prerequisites

- Python 3.10+
- MongoDB (or Podman/Docker to run it locally)

### Run Locally

```bash
# Clone the repo
git clone https://github.com/LiorHaim/poker-trainer-web.git
cd poker-trainer-web

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start MongoDB + run the app (uses Podman)
make local-run
```

The app will be available at **http://localhost:8080**.

### Developing

```bash
pip install -r requirements-dev.txt
make check          # lint + chart validation + tests, same as CI
```

### Try it without installing anything

If a deployment is already running, open its route:

```bash
oc project poker-trainer && make url
```

### Run with Docker

```bash
docker build -t poker-trainer .
docker run -p 8080:8080 -e MONGO_URI="mongodb://host.docker.internal:27017/poker" poker-trainer
```

## Makefile Commands

| Command | Description |
|---------|-------------|
| `make local-run` | Start MongoDB via Podman and run the app in debug mode |
| `make check` | Everything CI runs: lint, chart validation, tests |
| `make test` | Run the test suite (pytest) |
| `make lint` | Run ruff |
| `make validate-charts` | Validate every strategy chart against the schema |
| `make derive-mixes` | Recompute which hands are close decisions (run after editing ranges) |
| `make dev-install` | Install dev dependencies (pytest, ruff) |
| `make deploy` | Build and deploy to OpenShift (generates `SECRET_KEY` on first run) |
| `make ensure-secret` | Create the `SECRET_KEY` secret if it does not exist |
| `make update` | Rebuild and redeploy after code changes |
| `make logs` | Tail application logs |
| `make url` | Print the live application URL |
| `make clean` | Delete the OpenShift project |
| `make db-start` | Start a local MongoDB container |
| `make db-stop` | Stop the local MongoDB container |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health/live` | Liveness — never touches the database |
| `GET` | `/api/health/ready` | Readiness — pings the database |
| `POST` | `/api/auth/register` | Create a new account |
| `POST` | `/api/auth/login` | Log in |
| `POST` | `/api/auth/logout` | Log out |
| `GET` | `/api/auth/me` | Check current session |
| `POST` | `/api/start` | Start a training session; returns the first hand and a signed token |
| `POST` | `/api/act` | Submit an action (FOLD/CALL/RAISE) with the hand's token |
| `POST` | `/api/next` | Get the next hand (send the current token) |
| `GET` | `/api/statistics` | Get user stats |
| `POST` | `/api/statistics/clear` | Reset user stats |
| `GET` | `/api/leaderboard` | Get the leaderboard |
| `GET` | `/api/charts` | List all strategy charts |
| `GET` | `/api/chart/<key>` | Get a specific chart's data |
| `GET` | `/api/music` | List available background tracks |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGO_URI` | `mongodb://localhost:27017/poker` | MongoDB connection string |
| `SECRET_KEY` | Auto-generated | Signs session cookies **and training tokens**. Required in production, and every worker/replica must share the same value |
| `FLASK_ENV` | — | Set to `production` for secure cookies |
| `FLASK_DEBUG` | `0` | Set to `1` for debug mode |
| `CHART_VALIDATION` | — | Set to `strict` to refuse to start if any strategy chart fails validation |
| `GUNICORN_WORKERS` | `2` | Worker processes in the container |

## License

This project is for personal use and learning purposes.

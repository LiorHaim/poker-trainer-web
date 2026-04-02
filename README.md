# Poker Trainer Web

A web-based Texas Hold'em preflop trainer that helps you drill GTO-based preflop decisions, get instant feedback, and track your accuracy over time.

Built with Flask, MongoDB, and a lo-fi themed frontend.

## Features

- **52 Strategy Charts** — covers all key 6-Max 100BB spots: RFI, vs RFI, 3-Bet, vs 3-Bet, vs 4-Bet, and Squeeze
- **Drill Mode** — continuous random hands across all loaded charts
- **Focus Mode** — practice a specific position or situation (e.g. "only BTN spots")
- **Instant Feedback** — see whether your action matches the reference strategy, with a coaching explanation
- **Visual Range Matrix** — view the full strategy chart with your hand highlighted
- **Performance Tracking** — accuracy stats broken down by position and stack depth
- **Leaderboard** — compete with other users
- **Lo-fi Music Player** — ambient background music while you train
- **User Accounts** — register/login to persist stats across sessions

## Strategy Charts Included

All charts are for **Cash Game, 6-Max, 100BB effective stacks**:

| Spot | Charts |
|------|--------|
| RFI (open raise) | UTG, MP, CO, BTN, SB |
| vs RFI (facing open) | BB vs all positions, SB vs BTN/CO/MP/UTG, BTN vs UTG/MP/CO, CO vs UTG/MP |
| 3-Bet | SB & BB 3-bet vs all openers |
| vs 3-Bet | UTG/MP/CO/BTN vs various 3-bettors |
| vs 4-Bet | UTG/MP/CO/SB facing 4-bets |
| Squeeze | SB & BB squeeze vs opener+caller combos |

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

### Run with Docker

```bash
docker build -t poker-trainer .
docker run -p 8080:8080 -e MONGO_URI="mongodb://host.docker.internal:27017/poker" poker-trainer
```

## Makefile Commands

| Command | Description |
|---------|-------------|
| `make local-run` | Start MongoDB via Podman and run the app in debug mode |
| `make test` | Run the test suite |
| `make deploy` | Build and deploy to OpenShift |
| `make update` | Rebuild and redeploy after code changes |
| `make logs` | Tail application logs |
| `make url` | Print the live application URL |
| `make clean` | Delete the OpenShift project |
| `make db-start` | Start a local MongoDB container |
| `make db-stop` | Stop the local MongoDB container |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/auth/register` | Create a new account |
| `POST` | `/api/auth/login` | Log in |
| `POST` | `/api/auth/logout` | Log out |
| `GET` | `/api/auth/me` | Check current session |
| `POST` | `/api/start` | Start a training session |
| `POST` | `/api/act` | Submit an action (FOLD/CALL/RAISE) |
| `GET` | `/api/next` | Get the next hand |
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
| `SECRET_KEY` | Auto-generated | Flask session secret (required in production) |
| `FLASK_ENV` | — | Set to `production` for secure cookies |
| `FLASK_DEBUG` | `0` | Set to `1` for debug mode |

## License

This project is for personal use and learning purposes.

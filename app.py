import logging
import os
import random
import secrets
import sys
import time
from collections import defaultdict

from flask import Flask, jsonify, request, send_from_directory, session

from logic.scenario import Action, Position, PreflopAction, TrainingResult, TrainingScenario, get_random_hand
from logic.statistics_db import StatisticsManagerDB
from logic.strategy import StrategyManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_url_path='')

# --- Security: Secret Key ---
secret_key = os.environ.get("SECRET_KEY")
if not secret_key:
    if os.environ.get("FLASK_ENV") == "production":
        logger.error("SECRET_KEY environment variable is required in production!")
        sys.exit(1)
    secret_key = secrets.token_hex(32)
    logger.warning("Using auto-generated secret key. Set SECRET_KEY env var for production!")
app.secret_key = secret_key

# --- Security: Cookie Configuration ---
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)
if os.environ.get("FLASK_ENV") == "production":
    app.config['SESSION_COOKIE_SECURE'] = True

# --- Constants ---
STARTING_BANKROLL = 10000
CORRECT_REWARD = 100
INCORRECT_PENALTY = 100
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/poker")

# --- Rate Limiting (in-memory, per-process) ---
_rate_limits = defaultdict(list)

def check_rate_limit(key, max_attempts=10, window=60):
    """Simple in-memory rate limiter. Returns True if rate limited."""
    now = time.time()
    _rate_limits[key] = [t for t in _rate_limits[key] if now - t < window]
    if len(_rate_limits[key]) >= max_attempts:
        return True
    _rate_limits[key].append(now)
    return False

# --- Security Headers ---
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response

# --- Initialize Logic ---
try:
    logger.info("Initializing StrategyManager...")
    strategy_mgr = StrategyManager("strategy_charts")
    stats_mgr = StatisticsManagerDB(MONGO_URI)
    logger.info(f"Logic initialized. {len(strategy_mgr.chart_metadata)} charts loaded.")
except Exception as e:
    logger.error(f"FATAL ERROR during initialization: {e}", exc_info=True)
    strategy_mgr = None
    stats_mgr = None

# --- Per-User Game State ---
# Replaces the shared TrainingEngine singleton to prevent race conditions
# between concurrent users. Each user's scenario and available charts are
# stored independently. With gunicorn, this is per-worker (acceptable for
# small-scale; use Redis for production scale).
_user_state = {}


# --- Stateless Game Logic Helpers ---

def filter_scenarios(settings):
    """Filter available charts based on user settings. No shared mutable state."""
    available = []
    game_type_prefix = "cash" if settings.get("game_type") == "Cash Game" else "mtt"
    table_size = int(settings.get("table_size", 6))
    stack_depths = [int(x) for x in settings.get("stack_depths", [100])]
    mode = settings.get("training_mode", "Drill")
    focus_pos = settings.get("focus_position")
    focus_situation = settings.get("focus_situation")

    for key, meta in strategy_mgr.chart_metadata.items():
        if meta.get("game_type") != game_type_prefix: continue
        if int(meta.get("table_size", 0)) != table_size: continue
        if int(meta.get("stack_depth", 0)) not in stack_depths: continue
        if mode == "Focus" and focus_pos and str(meta.get("hero_position")) != str(focus_pos): continue
        if mode == "Focus" and focus_situation and str(meta.get("situation")) != str(focus_situation): continue
        meta_copy = dict(meta)
        meta_copy['chart_key'] = key
        available.append(meta_copy)
    return available


def generate_scenario(available_scenarios):
    """Generate a random scenario from available charts. No shared mutable state."""
    if not available_scenarios:
        return None
    scenario_meta = random.choice(available_scenarios)
    hand = get_random_hand()
    chart_key = scenario_meta["chart_key"]
    situation = scenario_meta.get("situation", "RFI")
    actions_before_hero = []
    hero_open_size = 0.0
    hero_3bet_size = 0.0

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
            hero_open_size = 3.0
            hero_3bet_size = 9.0
            actions_before_hero = [PreflopAction(position=villain_pos, action=Action.RAISE, size_bb=25.0)]
        elif situation == "squeeze":
            opener_pos = Position(scenario_meta["opener_position"])
            caller_pos = Position(scenario_meta["caller_position"])
            actions_before_hero = [
                PreflopAction(position=opener_pos, action=Action.RAISE, size_bb=3.0),
                PreflopAction(position=caller_pos, action=Action.CALL, size_bb=3.0)
            ]
        elif situation == "3Bet":
            villain_pos = Position(scenario_meta["villain_position"])
            actions_before_hero = [PreflopAction(position=villain_pos, action=Action.RAISE, size_bb=3.0)]
    except (KeyError, ValueError):
        situation = "RFI"
        actions_before_hero = []

    return TrainingScenario(
        table_size=int(scenario_meta["table_size"]),
        effective_stack_bb=int(scenario_meta["stack_depth"]),
        hero_position=Position(scenario_meta["hero_position"]),
        hero_hand=hand,
        actions_before_hero=actions_before_hero,
        chart_key=chart_key,
        situation=situation,
        hero_open_size_bb=hero_open_size,
        hero_3bet_size_bb=hero_3bet_size
    )


def evaluate_action(scenario, user_action):
    """Evaluate user's action against the strategy chart. No shared mutable state."""
    chart_key = scenario.chart_key
    compiled_chart = strategy_mgr.get_compiled_chart(chart_key)

    if not chart_key or not compiled_chart:
        return TrainingResult(scenario, user_action, Action.FOLD, "Error", False, {})

    rec_data = strategy_mgr.get_recommended_action(chart_key, scenario.hero_hand)
    if not rec_data:
        rec_data = {"action": Action.FOLD, "explanation": "Error"}

    return TrainingResult(
        scenario=scenario,
        user_action=user_action,
        correct_action=rec_data["action"],
        explanation=rec_data["explanation"],
        is_correct=(user_action == rec_data["action"]),
        compiled_chart=compiled_chart
    )


def serialize_chart(chart):
    if not chart: return {}
    json_chart = {}
    for hand, data in chart.items():
        json_chart[hand] = {
            "action": data["action"].value,
            "explanation": data["explanation"]
        }
    return json_chart


def serialize_scenario(sc):
    if not sc: return None
    return {
        "hero_pos": sc.hero_position.value,
        "stack": sc.effective_stack_bb,
        "pot": sc.pot_bb,
        "situation": sc.situation,
        "actions": [{"pos": a.position.value, "act": a.action.value, "amt": a.size_bb} for a in sc.actions_before_hero],
        "card1": {"rank": sc.hero_hand.card1.rank, "suit": sc.hero_hand.card1.suit},
        "card2": {"rank": sc.hero_hand.card2.rank, "suit": sc.hero_hand.card2.suit},
        "to_call": sc.to_call_bb
    }


# --- Static Routes ---

@app.route('/')
def root():
    return send_from_directory('static', 'index.html')

@app.route('/assets/<path:path>')
def send_asset(path):
    return send_from_directory('assets', path)

@app.route('/api/health', methods=['GET'])
def health_check():
    health_status = {
        "status": "healthy",
        "charts_loaded": len(strategy_mgr.chart_metadata) if strategy_mgr else 0,
        "db_connected": stats_mgr is not None,
    }
    status_code = 200 if strategy_mgr and stats_mgr else 503
    return jsonify(health_status), status_code

@app.route('/api/music', methods=['GET'])
def get_music_list():
    try:
        files = [f for f in os.listdir('assets') if f.endswith('.mp3')]
        return jsonify(sorted(files))
    except Exception as e:
        logger.error(f"Error listing music files: {e}", exc_info=True)
        return jsonify([])

@app.route('/api/charts', methods=['GET'])
def list_charts():
    charts = []
    for key, meta in strategy_mgr.chart_metadata.items():
        charts.append({"key": key, "description": meta.get("description", key)})
    charts.sort(key=lambda x: x['key'])
    return jsonify(charts)

@app.route('/api/chart/<chart_key>', methods=['GET'])
def get_chart(chart_key):
    if not chart_key.replace('_', '').replace('-', '').isalnum():
        return jsonify({"error": "Invalid chart key"}), 400
    compiled = strategy_mgr.get_compiled_chart(chart_key)
    if not compiled: return jsonify({"error": "Chart not found"}), 404
    return jsonify({
        "key": chart_key,
        "matrix": serialize_chart(compiled),
        "metadata": strategy_mgr.chart_metadata.get(chart_key, {})
    })


# --- Auth Routes ---

def validate_username(username):
    if not username or not isinstance(username, str):
        return False, "Username must be a string"
    if len(username) < 3 or len(username) > 20:
        return False, "Username must be between 3 and 20 characters"
    if not username.replace('_', '').isalnum():
        return False, "Username can only contain letters, numbers, and underscores"
    return True, None

def validate_password(password):
    if not password or not isinstance(password, str):
        return False, "Password must be a string"
    if len(password) < 6:
        return False, "Password must be at least 6 characters long"
    return True, None

@app.route('/api/auth/register', methods=['POST'])
def register():
    client_ip = request.remote_addr
    if check_rate_limit(f"register:{client_ip}", max_attempts=5, window=60):
        return jsonify({"error": "Too many attempts. Try again later."}), 429

    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.json
    username = data.get('username', '').strip() if data else ''
    password = data.get('password', '') if data else ''

    if not username or not password:
        return jsonify({"error": "Missing credentials"}), 400

    valid, error_msg = validate_username(username)
    if not valid:
        return jsonify({"error": error_msg}), 400

    valid, error_msg = validate_password(password)
    if not valid:
        return jsonify({"error": error_msg}), 400

    try:
        if stats_mgr.create_user(username, password):
            session['user'] = username
            logger.info(f"New user registered: {username}")
            return jsonify({"success": True, "username": username})
        return jsonify({"error": "Username already taken"}), 400
    except Exception as e:
        logger.error(f"Error during registration: {e}", exc_info=True)
        return jsonify({"error": "Registration failed"}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    client_ip = request.remote_addr
    if check_rate_limit(f"login:{client_ip}", max_attempts=10, window=60):
        return jsonify({"error": "Too many login attempts. Try again later."}), 429

    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.json
    username = data.get('username', '').strip() if data else ''
    password = data.get('password', '') if data else ''

    if not username or not password:
        return jsonify({"error": "Missing credentials"}), 400

    try:
        if stats_mgr.verify_user(username, password):
            session['user'] = username
            logger.info(f"User logged in: {username}")
            bankroll = stats_mgr.get_bankroll(username)
            return jsonify({"success": True, "username": username, "bankroll": bankroll})
        logger.warning(f"Failed login attempt from {client_ip}")
        return jsonify({"error": "Invalid credentials"}), 401
    except Exception as e:
        logger.error(f"Error during login: {e}", exc_info=True)
        return jsonify({"error": "Login failed"}), 500

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    username = session.pop('user', None)
    if username:
        _user_state.pop(username, None)
    return jsonify({"success": True})

@app.route('/api/auth/me', methods=['GET'])
def check_auth():
    if 'user' in session:
        username = session['user']
        bankroll = stats_mgr.get_bankroll(username)
        return jsonify({"username": username, "bankroll": bankroll})
    return jsonify({"error": "Not logged in"}), 401


# --- Leaderboard (with per-process caching) ---
_leaderboard_cache = {"data": None, "timestamp": 0}
LEADERBOARD_CACHE_TTL = 60

@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    try:
        current_time = time.time()
        if _leaderboard_cache["data"] and (current_time - _leaderboard_cache["timestamp"]) < LEADERBOARD_CACHE_TTL:
            return jsonify(_leaderboard_cache["data"])
        data = stats_mgr.get_leaderboard()
        _leaderboard_cache["data"] = data
        _leaderboard_cache["timestamp"] = current_time
        return jsonify(data)
    except Exception as e:
        logger.error(f"Error getting leaderboard: {e}", exc_info=True)
        return jsonify({"error": "Failed to retrieve leaderboard"}), 500


# --- Game Routes (per-user state, no shared mutable singleton) ---

@app.route('/api/start', methods=['POST'])
def start():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    if not strategy_mgr:
        return jsonify({"error": "Server not initialized"}), 500
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    username = session['user']
    settings = request.json or {}
    if "game_type" not in settings: settings["game_type"] = "Cash Game"
    if "table_size" not in settings: settings["table_size"] = 6
    settings['stack_depths'] = [100]

    try:
        available = filter_scenarios(settings)
        if not available:
            return jsonify({"error": "No charts match these settings."}), 400

        scenario = generate_scenario(available)
        if not scenario:
            return jsonify({"error": "Failed to generate scenario"}), 500

        _user_state[username] = {"available": available, "scenario": scenario}
        return jsonify(serialize_scenario(scenario))
    except Exception as e:
        logger.error(f"Error starting training: {e}", exc_info=True)
        return jsonify({"error": "Failed to start training"}), 500

@app.route('/api/act', methods=['POST'])
def act():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    if not strategy_mgr:
        return jsonify({"error": "Server not initialized"}), 500
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    username = session['user']
    state = _user_state.get(username)
    if not state or not state.get("scenario"):
        return jsonify({"error": "No active scenario. Start training first."}), 400

    try:
        data = request.json
        if not data or 'action' not in data:
            return jsonify({"error": "Missing 'action' field"}), 400

        action_str = data['action']
        if action_str not in ('FOLD', 'CALL', 'RAISE'):
            return jsonify({"error": "Invalid action. Must be FOLD, CALL, or RAISE"}), 400

        action = Action[action_str]
        result = evaluate_action(state["scenario"], action)

        stats_mgr.log_decision(result, username)
        _leaderboard_cache["data"] = None
        _leaderboard_cache["timestamp"] = 0

        bankroll = stats_mgr.get_bankroll(username)

        return jsonify({
            "is_correct": result.is_correct,
            "explanation": result.explanation,
            "correct_action": result.correct_action.value,
            "chart": serialize_chart(result.compiled_chart),
            "hero_hand": result.scenario.hero_hand.range_notation,
            "bankroll": bankroll
        })
    except KeyError as e:
        logger.error(f"Invalid action key: {e}", exc_info=True)
        return jsonify({"error": f"Invalid action: {e}"}), 400
    except Exception as e:
        logger.error(f"Error processing action: {e}", exc_info=True)
        return jsonify({"error": "Failed to process action"}), 500

@app.route('/api/next', methods=['GET'])
def next_hand():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    username = session['user']
    state = _user_state.get(username)
    if not state or not state.get("available"):
        return jsonify({"error": "No training session active. Start training first."}), 400

    try:
        scenario = generate_scenario(state["available"])
        if not scenario:
            return jsonify({"error": "Failed to generate scenario"}), 500
        state["scenario"] = scenario
        return jsonify(serialize_scenario(scenario))
    except Exception as e:
        logger.error(f"Error getting next hand: {e}", exc_info=True)
        return jsonify({"error": "Failed to get next hand"}), 500


# --- Statistics ---

@app.route('/api/statistics', methods=['GET'])
def get_stats():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    u = session['user']
    try:
        return jsonify({
            "overall": stats_mgr.get_overall_accuracy(u),
            "by_pos": stats_mgr.get_accuracy_by_position(u),
            "by_stack": stats_mgr.get_accuracy_by_stack(u),
            "history": stats_mgr.get_recent_history(u)
        })
    except Exception as e:
        logger.error(f"Error getting statistics: {e}", exc_info=True)
        return jsonify({"error": "Failed to retrieve statistics"}), 500

@app.route('/api/statistics/clear', methods=['POST'])
def clear_stats():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        stats_mgr.clear_stats(session['user'])
        _leaderboard_cache["data"] = None
        _leaderboard_cache["timestamp"] = 0
        logger.info(f"Statistics cleared for user: {session['user']}")
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error clearing statistics: {e}", exc_info=True)
        return jsonify({"error": "Failed to clear statistics"}), 500


if __name__ == '__main__':
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host='0.0.0.0', port=8080, debug=debug_mode)

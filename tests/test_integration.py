"""
End-to-end checks against the real charts and the real request path.

This used to exercise `logic/trainer.py`, a module the app did not import - so
it tested a stale copy of the scenario logic while the code actually serving
requests went uncovered. `trainer.py` is gone; these drive `app.py`.
"""
import json
from pathlib import Path

import mongomock
import pytest

import app as application
from logic.chart_schema import ALL_HANDS
from logic.nodes import build_node
from logic.scenario import Action
from logic.statistics_db import StatisticsManagerDB
from logic.strategy import StrategyManager

CHART_DIR = Path(__file__).resolve().parent.parent / "strategy_charts"


@pytest.fixture
def stats(monkeypatch):
    """
    The real statistics store on an in-memory MongoDB.

    A hand-written fake drifted out of step with the interface the app calls -
    it was missing the review-queue methods added for adaptive drilling, and
    the tests only noticed because the request blew up.
    """
    monkeypatch.setattr("logic.statistics_db.MongoClient", mongomock.MongoClient)
    return StatisticsManagerDB("mongodb://localhost:27017/poker")


@pytest.fixture
def client(monkeypatch, stats):
    monkeypatch.setattr(application, "stats_mgr", stats)
    monkeypatch.setattr(application, "strategy_mgr", StrategyManager(CHART_DIR))
    application.app.config["TESTING"] = True
    # Every test registers from the same address; without this the limiter
    # starts refusing them partway through the file.
    application._rate_limits.clear()

    with application.app.test_client() as test_client:
        # The real store verifies credentials, so the account has to exist.
        registered = test_client.post(
            "/api/auth/register", json={"username": "tester", "password": "password1"}
        )
        assert registered.status_code == 200, registered.get_json()
        yield test_client


# --- The charts themselves --------------------------------------------------

def test_every_chart_builds_a_scenario():
    """
    A chart that passes validation must also be playable: its metadata has to
    resolve to a concrete spot with a pot and an amount to call.
    """
    manager = StrategyManager(CHART_DIR)
    assert manager.charts
    for key, metadata in manager.chart_metadata.items():
        node = build_node(metadata)
        assert node.pot_bb > 0, key
        assert node.to_call_bb >= 0, key
        assert node.action_text, key
        assert node.raise_label, key


def test_every_chart_answers_every_hand():
    manager = StrategyManager(CHART_DIR)
    for key in manager.charts:
        compiled = manager.get_compiled_chart(key)
        assert set(compiled) == ALL_HANDS, key
        for hand, data in compiled.items():
            assert isinstance(data["action"], Action), f"{key} {hand}"


def test_pot_odds_match_the_declared_sizings():
    """
    The amount to call has to come from the sizes the chart was built for. It
    used to come from a hardcoded table, so a chart built for a 2.5bb open was
    drilled at 3.0bb.
    """
    for path in CHART_DIR.glob("*.json"):
        metadata = json.loads(path.read_text())["metadata"]
        if metadata["situation"] != "vs_RFI":
            continue
        node = build_node(metadata)
        open_bb = metadata["sizings"]["open_bb"]
        posted = {"BB": 1.0, "SB": 0.5}.get(metadata["hero_position"], 0.0)
        assert node.to_call_bb == pytest.approx(open_bb - posted), path.name


# --- The request path -------------------------------------------------------

def test_full_game_loop(client):
    started = client.post("/api/start", json={})
    assert started.status_code == 200
    scenario = started.get_json()
    for field in ("hero_pos", "situation", "pot", "to_call", "card1", "card2",
                  "raise_label", "action_text", "token"):
        assert field in scenario

    acted = client.post("/api/act", json={"action": "FOLD", "token": scenario["token"]})
    assert acted.status_code == 200
    result = acted.get_json()
    assert isinstance(result["is_correct"], bool)
    assert result["correct_action"] in ("FOLD", "CALL", "RAISE")
    assert len(result["chart"]) == 169

    assert client.post("/api/next", json={"token": scenario["token"]}).status_code == 200


def test_the_answer_is_graded_against_the_hand_in_the_token(client):
    """
    The server keeps nothing between requests, so the token has to carry the
    spot. Grading must use the hand it names, not a freshly dealt one.
    """
    scenario = client.post("/api/start", json={}).get_json()
    first = client.post("/api/act", json={"action": "FOLD", "token": scenario["token"]}).get_json()
    second = client.post("/api/act", json={"action": "FOLD", "token": scenario["token"]}).get_json()
    assert first["hero_hand"] == second["hero_hand"]
    assert first["correct_action"] == second["correct_action"]


def test_a_tampered_token_is_rejected(client):
    scenario = client.post("/api/start", json={}).get_json()
    forged = scenario["token"][:-5] + "xxxxx"
    assert client.post("/api/act", json={"action": "FOLD", "token": forged}).status_code == 400


def test_a_token_from_another_user_is_rejected(client):
    """Signed tokens are bound to the account they were issued to."""
    scenario = client.post("/api/start", json={}).get_json()
    with application.app.test_client() as other:
        other.post("/api/auth/register", json={"username": "someone_else", "password": "password1"})
        rejected = other.post("/api/act", json={"action": "FOLD", "token": scenario["token"]})
        assert rejected.status_code == 400


def test_the_session_survives_a_restart(client, monkeypatch):
    """
    What the per-worker dict could not do: a hand started against one process
    can be answered by another, as long as they share a secret key.
    """
    scenario = client.post("/api/start", json={}).get_json()
    monkeypatch.setattr(application, "strategy_mgr", StrategyManager(CHART_DIR))
    answered = client.post("/api/act", json={"action": "FOLD", "token": scenario["token"]})
    assert answered.status_code == 200


def test_many_scenarios_across_every_chart(client):
    """Catch a chart whose metadata the engine cannot turn into a spot."""
    token = client.post("/api/start", json={}).get_json()["token"]
    seen = set()
    for _ in range(300):
        scenario = client.post("/api/next", json={"token": token}).get_json()
        assert "hero_pos" in scenario, scenario
        seen.add(scenario["situation"])
        token = scenario["token"]
    assert {"RFI", "vs_RFI"} <= seen


def test_focus_mode_filters_by_position(client):
    started = client.post("/api/start", json={"training_mode": "Focus", "focus_position": "BTN"})
    assert started.status_code == 200
    scenario = started.get_json()
    assert scenario["hero_pos"] == "BTN"
    # The settings ride in the token, so the filter survives without server state.
    for _ in range(25):
        scenario = client.post("/api/next", json={"token": scenario["token"]}).get_json()
        assert scenario["hero_pos"] == "BTN"


def test_acting_without_a_token_is_rejected(client):
    assert client.post("/api/act", json={"action": "FOLD"}).status_code == 400
    assert client.post("/api/next", json={}).status_code == 400


def test_invalid_action_is_rejected(client):
    token = client.post("/api/start", json={}).get_json()["token"]
    assert client.post("/api/act", json={"action": "LIMP", "token": token}).status_code == 400


def test_a_missed_hand_comes_back(client, stats):
    """
    The drill adapts: answer a spot wrong and it is scheduled to return, which
    is the whole point of tracking decisions in the first place.
    """
    scenario = client.post("/api/start", json={}).get_json()
    wrong = "FOLD" if scenario["raise_label"] else "FOLD"
    client.post("/api/act", json={"action": wrong, "token": scenario["token"]})

    # Whether that answer was wrong depends on the hand dealt, so drive hands
    # until one is missed rather than assuming.
    token = scenario["token"]
    for _ in range(40):
        if stats.count_tracked_reviews("tester"):
            break
        scenario = client.post("/api/next", json={"token": token}).get_json()
        token = scenario["token"]
        client.post("/api/act", json={"action": "RAISE", "token": token})
    assert stats.count_tracked_reviews("tester") > 0, "no missed hand was ever tracked"


def test_statistics_report_leaks(client):
    scenario = client.post("/api/start", json={}).get_json()
    client.post("/api/act", json={"action": "FOLD", "token": scenario["token"]})
    payload = client.get("/api/statistics").get_json()
    for field in ("overall", "by_pos", "by_chart", "worst_hands", "review_queue", "history"):
        assert field in payload, field
    assert "by_stack" not in payload, "stack depth is constant across the chart set"


def test_game_routes_require_a_session():
    application.app.config["TESTING"] = True
    with application.app.test_client() as anonymous:
        assert anonymous.post("/api/start", json={}).status_code == 401
        assert anonymous.post("/api/act", json={"action": "FOLD"}).status_code == 401
        assert anonymous.post("/api/next", json={}).status_code == 401

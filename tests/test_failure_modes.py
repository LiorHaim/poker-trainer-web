"""
What the app does when the database is gone.

Every assertion here failed before this change. With MongoDB scaled to zero on
a live cluster, the app reported `200 {"db_connected": true, "status":
"healthy"}`, both replicas stayed Ready and kept taking traffic, a registration
was refused with "Username already taken", and a valid login was refused with
"Invalid credentials" - telling a user their correct password was wrong.
"""
import mongomock
import pytest

import app as application
from logic.statistics_db import StatisticsManagerDB, StatsUnavailable
from logic.strategy import StrategyManager
from tests.test_integration import CHART_DIR

#: Nothing is listening here. MongoClient connects lazily, so constructing
#: against it succeeds - which is exactly how the old health check was fooled.
DEAD_URI = "mongodb://127.0.0.1:59999/poker"


@pytest.fixture
def dead_stats():
    # 50ms rather than the production 2s: these tests exercise the failure
    # path repeatedly and should not spend a minute waiting out real timeouts.
    return StatisticsManagerDB(DEAD_URI, server_selection_timeout_ms=50)


@pytest.fixture
def live_stats(monkeypatch):
    monkeypatch.setattr("logic.statistics_db.MongoClient", mongomock.MongoClient)
    return StatisticsManagerDB("mongodb://localhost:27017/poker")


def client_for(monkeypatch, stats):
    monkeypatch.setattr(application, "stats_mgr", stats)
    monkeypatch.setattr(application, "strategy_mgr", StrategyManager(CHART_DIR))
    application.app.config["TESTING"] = True
    application._rate_limits.clear()
    return application.app.test_client()


# --- The manager constructs against nothing ---------------------------------

def test_manager_constructs_against_a_dead_database(dead_stats):
    """
    This is why the old probe could never report a problem: MongoClient is
    lazy and index creation swallows its own failure, so there is no error to
    observe at construction time.
    """
    assert dead_stats is not None


def test_ping_is_what_actually_detects_it(dead_stats, live_stats):
    assert dead_stats.ping() is False
    assert live_stats.ping() is True


# --- Probes -----------------------------------------------------------------

def test_liveness_ignores_the_database(monkeypatch, dead_stats):
    """A dependency outage must not restart the process."""
    client = client_for(monkeypatch, dead_stats)
    for path in ("/api/health", "/api/health/live"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.get_json()["status"] == "alive"


def test_readiness_fails_when_the_database_is_gone(monkeypatch, dead_stats):
    client = client_for(monkeypatch, dead_stats)
    response = client.get("/api/health/ready")
    assert response.status_code == 503
    assert response.get_json()["db_connected"] is False


def test_readiness_passes_when_the_database_answers(monkeypatch, live_stats):
    client = client_for(monkeypatch, live_stats)
    response = client.get("/api/health/ready")
    assert response.status_code == 200
    assert response.get_json()["db_connected"] is True


# --- Honest errors instead of confident wrong answers -----------------------

def test_login_does_not_claim_the_password_is_wrong(monkeypatch, dead_stats):
    """The worst of the old behaviours: a correct password reported as invalid."""
    client = client_for(monkeypatch, dead_stats)
    response = client.post(
        "/api/auth/login", json={"username": "someone", "password": "password1"}
    )
    assert response.status_code == 503
    assert "Invalid credentials" not in response.get_json()["error"]


def test_register_does_not_claim_the_name_is_taken(monkeypatch, dead_stats):
    client = client_for(monkeypatch, dead_stats)
    response = client.post(
        "/api/auth/register", json={"username": "brandnew", "password": "password1"}
    )
    assert response.status_code == 503
    assert "already taken" not in response.get_json()["error"]


def test_leaderboard_does_not_claim_there_are_no_players(monkeypatch, dead_stats):
    client = client_for(monkeypatch, dead_stats)
    assert client.get("/api/leaderboard").status_code == 503


def test_bankroll_does_not_report_the_starting_amount(dead_stats):
    with pytest.raises(StatsUnavailable):
        dead_stats.get_bankroll("hero")


@pytest.mark.parametrize(
    "method",
    ["get_overall_accuracy", "get_accuracy_by_position", "get_accuracy_by_chart",
     "get_worst_hands", "get_recent_history"],
)
def test_statistics_reads_do_not_report_zero(dead_stats, method):
    """'0 hands, 0%' is a claim about the data, not an absence of one."""
    with pytest.raises(StatsUnavailable):
        getattr(dead_stats, method)("hero")


# --- Deliberate exceptions to the policy ------------------------------------

def test_logging_a_decision_never_breaks_the_drill(dead_stats):
    """Losing one hand beats interrupting the session the user is in."""
    from tests.test_statistics_db import a_result

    dead_stats.log_decision(a_result(), "hero")  # must not raise


def test_review_queue_degrades_to_random_drilling(dead_stats):
    """Adaptive drilling turning off is a worse drill, not a wrong answer."""
    assert dead_stats.get_due_reviews("hero") == []
    assert dead_stats.count_tracked_reviews("hero") == 0

"""
Tests for the statistics store, against an in-memory MongoDB.

This module had no tests at all, and it holds the scoring, the leaderboard and
now the review schedule - the parts where being quietly wrong is least visible.
"""
import mongomock
import pytest

from logic.scenario import Action, Position, TrainingResult, TrainingScenario, random_hand_of
from logic.statistics_db import (
    CORRECT_REWARD,
    INCORRECT_PENALTY,
    STARTING_BANKROLL,
    StatisticsManagerDB,
    bankroll_from,
)

CHART = "cash_6max_100bb_BTN_RFI"


@pytest.fixture
def stats(monkeypatch):
    monkeypatch.setattr("logic.statistics_db.MongoClient", mongomock.MongoClient)
    return StatisticsManagerDB("mongodb://localhost:27017/poker")


def a_result(hand="AA", correct=True, chart=CHART, position=Position.BTN):
    scenario = TrainingScenario(
        hero_position=position,
        hero_hand=random_hand_of(hand),
        chart_key=chart,
    )
    return TrainingResult(
        scenario=scenario,
        user_action=Action.RAISE if correct else Action.FOLD,
        correct_action=Action.RAISE,
        explanation="because",
        is_correct=correct,
        compiled_chart={},
    )


def play(stats, username="hero", **kwargs):
    result = a_result(**kwargs)
    stats.log_decision(result, username)
    return result


# --- Scoring ----------------------------------------------------------------

def test_bankroll_formula():
    assert bankroll_from(0, 0) == STARTING_BANKROLL
    assert bankroll_from(3, 3) == STARTING_BANKROLL + 3 * CORRECT_REWARD
    assert bankroll_from(0, 2) == STARTING_BANKROLL - 2 * INCORRECT_PENALTY


def test_bankroll_tracks_decisions(stats):
    assert stats.get_bankroll("hero") == STARTING_BANKROLL
    play(stats, correct=True)
    play(stats, correct=True)
    play(stats, correct=False)
    assert stats.get_bankroll("hero") == bankroll_from(2, 3)


def test_bankroll_is_a_point_read_not_an_aggregation(stats):
    """The totals document is what is read; history is not rescanned."""
    for _ in range(5):
        play(stats, correct=True)
    totals = stats.totals.find_one({"username": "hero"})
    assert totals["total"] == 5 and totals["correct"] == 5


def test_totals_are_backfilled_for_history_written_before_them(stats):
    """Users with history but no totals document must not read as a fresh account."""
    for _ in range(4):
        play(stats, correct=True)
    stats.totals.delete_many({})
    assert stats.get_bankroll("hero") == bankroll_from(4, 4)
    assert stats.totals.find_one({"username": "hero"})["total"] == 4


def test_stats_are_scoped_per_user(stats):
    play(stats, username="hero", correct=True)
    play(stats, username="villain", correct=False)
    assert stats.get_bankroll("hero") == bankroll_from(1, 1)
    assert stats.get_bankroll("villain") == bankroll_from(0, 1)


def test_clearing_removes_everything_for_that_user(stats):
    play(stats, username="hero", correct=False)
    play(stats, username="villain", correct=False)
    stats.clear_stats("hero")
    assert stats.get_bankroll("hero") == STARTING_BANKROLL
    assert stats.count_tracked_reviews("hero") == 0
    assert stats.get_bankroll("villain") == bankroll_from(0, 1)


# --- Accounts ---------------------------------------------------------------

def test_passwords_are_hashed(stats):
    stats.create_user("hero", "password1")
    stored = stats.users.find_one({"username": "hero"})
    assert stored["password"] != "password1"
    assert stats.verify_user("hero", "password1")
    assert not stats.verify_user("hero", "wrong")


def test_duplicate_users_are_refused(stats):
    assert stats.create_user("hero", "password1")
    assert not stats.create_user("hero", "password2")


# --- Leaks ------------------------------------------------------------------

def test_weakest_charts_need_enough_hands_to_count(stats):
    """Three hands at 0% is noise, not a leak."""
    for _ in range(2):
        play(stats, chart="rarely_seen", correct=False)
    for i in range(6):
        play(stats, chart="often_seen", correct=i < 2)

    worst = stats.get_accuracy_by_chart("hero", min_hands=5)
    assert "rarely_seen" not in worst
    assert worst["often_seen"]["total"] == 6
    assert worst["often_seen"]["percent"] == pytest.approx(100 * 2 / 6)


def test_worst_hands_excludes_the_ones_always_played_right(stats):
    for _ in range(4):
        play(stats, hand="AA", correct=True)
    for i in range(4):
        play(stats, hand="72o", correct=i == 0)

    worst = stats.get_worst_hands("hero", min_hands=3)
    assert "AA" not in worst
    assert worst["72o"]["percent"] == pytest.approx(25.0)


# --- Review schedule --------------------------------------------------------

def test_a_correct_first_answer_is_not_tracked(stats):
    play(stats, correct=True)
    assert stats.count_tracked_reviews("hero") == 0


def test_a_miss_enters_the_queue(stats):
    play(stats, hand="72o", correct=False)
    assert stats.count_tracked_reviews("hero") == 1


def test_a_missed_spot_becomes_due_after_a_few_more_hands(stats):
    play(stats, hand="72o", correct=False)
    assert stats.get_due_reviews("hero") == []  # not yet

    for _ in range(5):
        play(stats, hand="AA", correct=True)

    due = stats.get_due_reviews("hero")
    assert [item.hand for item in due] == ["72o"]
    assert due[0].chart_key == CHART


def test_getting_it_right_repeatedly_retires_the_item(stats):
    play(stats, hand="72o", correct=False)
    assert stats.count_tracked_reviews("hero") == 1
    for _ in range(10):
        play(stats, hand="72o", correct=True)
    assert stats.count_tracked_reviews("hero") == 0, "a spot answered right repeatedly should retire"


def test_missing_it_again_keeps_it_in_the_queue(stats):
    play(stats, hand="72o", correct=False)
    for _ in range(6):
        play(stats, hand="72o", correct=False)
    assert stats.count_tracked_reviews("hero") == 1


def test_review_items_are_scoped_per_user(stats):
    play(stats, username="hero", hand="72o", correct=False)
    assert stats.count_tracked_reviews("villain") == 0

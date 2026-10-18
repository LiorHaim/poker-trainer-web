"""
Tests for signed training tokens.

The token replaces a server-side dict that made the app correct only at a
single gunicorn worker. Since the client now holds the state, the signature is
the only thing stopping a user from editing the spot after seeing the answer.
"""
import time

import pytest

from logic.session_token import InvalidToken, TrainingToken, issue, verify

SECRET = "test-secret"
OTHER_SECRET = "a-different-secret"


def a_token(**overrides):
    fields = {
        "username": "hero",
        "settings": {"game_type": "Cash Game", "table_size": 6},
        "chart_key": "cash_6max_100bb_BTN_RFI",
        "hand": "AhKs",
    }
    fields.update(overrides)
    return TrainingToken(**fields)


def test_round_trip():
    token = a_token()
    assert verify(SECRET, issue(SECRET, token), "hero") == token


def test_settings_survive():
    token = a_token(settings={"training_mode": "Focus", "focus_position": "BTN"})
    assert verify(SECRET, issue(SECRET, token), "hero").settings["focus_position"] == "BTN"


def test_tampering_is_rejected():
    raw = issue(SECRET, a_token())
    tampered = raw[:-4] + ("aaaa" if not raw.endswith("aaaa") else "bbbb")
    with pytest.raises(InvalidToken):
        verify(SECRET, tampered, "hero")


def test_a_token_from_another_server_is_rejected():
    with pytest.raises(InvalidToken):
        verify(SECRET, issue(OTHER_SECRET, a_token()), "hero")


def test_a_token_for_another_user_is_rejected():
    """A leaked token must not let someone else answer that hand."""
    with pytest.raises(InvalidToken):
        verify(SECRET, issue(SECRET, a_token(username="hero")), "villain")


def test_expired_token_is_rejected():
    raw = issue(SECRET, a_token())
    with pytest.raises(InvalidToken):
        verify(SECRET, raw, "hero", max_age=-1)


def test_fresh_token_within_max_age_is_accepted():
    raw = issue(SECRET, a_token())
    time.sleep(0.01)
    assert verify(SECRET, raw, "hero", max_age=60).hand == "AhKs"


@pytest.mark.parametrize("raw", [None, "", 42, [], "not-a-token"])
def test_junk_is_rejected(raw):
    with pytest.raises(InvalidToken):
        verify(SECRET, raw, "hero")


def test_token_without_a_hand_is_still_valid():
    """A session token carries settings before any hand is dealt."""
    token = verify(SECRET, issue(SECRET, a_token(chart_key=None, hand=None)), "hero")
    assert token.chart_key is None
    assert token.settings


def test_malformed_payload_is_rejected():
    from itsdangerous import URLSafeTimedSerializer

    from logic.session_token import SALT

    raw = URLSafeTimedSerializer(SECRET, salt=SALT).dumps(["not", "a", "dict"])
    with pytest.raises(InvalidToken):
        verify(SECRET, raw, "hero")

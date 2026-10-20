"""
Signed training tokens.

The server used to keep each user's current scenario in a module-level dict.
That made the app correct only at a single gunicorn worker - start a hand on
worker A and answer it on worker B and you get "No active scenario" - and the
dict grew without bound, since entries were only removed on an explicit logout.

A training session is small enough to hand to the client instead: which charts
the session covers, and which hand is live. Signing it keeps the client from
editing the spot after seeing the answer, and makes the app horizontally
scalable with no shared store.

Each token carries a nonce, so a dealt hand can be answered exactly once - see
`StatisticsManagerDB.claim_answer`. Without it, re-submitting the same token
logged a fresh decision every time, which was not a theoretical replay attack
but something a user hit by clicking a button twice: the buttons stayed live
after the result was shown, so one dealt hand could be answered with all three
actions until one of them was right.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

#: Tokens older than this are rejected. Long enough to leave a hand open over a
#: coffee break, short enough that a leaked token is not useful for long.
MAX_AGE_SECONDS = 12 * 60 * 60

SALT = "poker-trainer-session"


class InvalidToken(ValueError):
    """Raised when a token is missing, tampered with, or too old."""


@dataclass(frozen=True)
class TrainingToken:
    """What the client is given between requests."""

    username: str
    settings: dict[str, Any]
    chart_key: str | None = None
    hand: str | None = None
    #: Identifies this specific deal, so answering it twice can be detected.
    nonce: str = field(default_factory=lambda: secrets.token_urlsafe(12))

    def to_payload(self) -> dict:
        return {
            "u": self.username,
            "s": self.settings,
            "c": self.chart_key,
            "h": self.hand,
            "n": self.nonce,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> TrainingToken:
        if not isinstance(payload, dict) or "u" not in payload:
            raise InvalidToken("malformed token payload")
        settings = payload.get("s")
        return cls(
            username=payload["u"],
            settings=settings if isinstance(settings, dict) else {},
            chart_key=payload.get("c"),
            hand=payload.get("h"),
            nonce=payload.get("n") or "",
        )


def _serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt=SALT)


def issue(secret: str, token: TrainingToken) -> str:
    return _serializer(secret).dumps(token.to_payload())


def verify(secret: str, raw: Any, username: str, max_age: int = MAX_AGE_SECONDS) -> TrainingToken:
    """
    Decode and check a token.

    The username is checked against the session as well as the signature, so a
    token cannot be used by a different account even if it leaks.
    """
    if not raw or not isinstance(raw, str):
        raise InvalidToken("no token supplied")
    try:
        payload = _serializer(secret).loads(raw, max_age=max_age)
    except SignatureExpired as exc:
        raise InvalidToken("token has expired") from exc
    except BadSignature as exc:
        raise InvalidToken("token signature is not valid") from exc

    token = TrainingToken.from_payload(payload)
    if token.username != username:
        raise InvalidToken("token belongs to a different user")
    return token

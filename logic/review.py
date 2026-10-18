"""
Spaced repetition over the user's own mistakes.

Every drill was uniformly random, so a hand you reliably get wrong came up no
more often than one you have never missed. The app was already recording every
decision and doing nothing with it.

This schedules review: miss a spot and it comes back soon, keep getting it
right and it backs off. The scheduling is a simplified SM-2 - the interval is a
count of hands rather than a number of days, because a training session is
measured in hands and a drill you will see again in six days is a drill you
will not see.

A review item is a (chart, hand class) pair, which is exactly what a training
token already carries, so replaying one costs nothing extra.
"""
from __future__ import annotations

from dataclasses import dataclass

#: How many further hands to wait before showing an item again, by how many
#: times it has been answered correctly in a row. Short at first, because the
#: point is to catch the mistake while it is still fresh.
INTERVALS = (3, 8, 20, 50, 120)

#: A lapse does not send an item all the way back to the start; it drops a
#: couple of steps, so a hand you mostly know does not flood the session.
LAPSE_STEP_BACK = 2

#: Share of hands drawn from the review queue when anything is due. The rest
#: stay random: a drill made entirely of past mistakes stops resembling poker,
#: and the point is to play the spot in context.
REVIEW_SHARE = 0.35


@dataclass(frozen=True)
class ReviewItem:
    """One scheduled spot."""

    chart_key: str
    hand: str
    streak: int = 0
    due_at: int = 0

    def next_after(self, correct: bool, hands_played: int) -> ReviewItem:
        """Reschedule after an answer. `hands_played` is the session-independent clock."""
        if correct:
            streak = min(self.streak + 1, len(INTERVALS) - 1)
        else:
            streak = max(self.streak - LAPSE_STEP_BACK, 0)
        return ReviewItem(
            chart_key=self.chart_key,
            hand=self.hand,
            streak=streak,
            due_at=hands_played + INTERVALS[streak],
        )

    @classmethod
    def first_miss(cls, chart_key: str, hand: str, hands_played: int) -> ReviewItem:
        """A spot just got wrong for the first time: show it again soon."""
        return cls(chart_key=chart_key, hand=hand, streak=0, due_at=hands_played + INTERVALS[0])

    def is_due(self, hands_played: int) -> bool:
        return hands_played >= self.due_at

    def is_retired(self) -> bool:
        """Answered correctly enough times in a row to stop tracking."""
        return self.streak >= len(INTERVALS) - 1


def due_items(items, hands_played: int) -> list[ReviewItem]:
    """Items ready to be shown again, most overdue first."""
    return sorted(
        (item for item in items if item.is_due(hands_played)),
        key=lambda item: item.due_at,
    )

"""
Tests for spaced repetition.

The scheduling has to do two things: bring a missed spot back soon enough to
catch the mistake while it is fresh, and back off fast enough that a hand the
user knows stops eating the session.
"""
from logic.review import INTERVALS, LAPSE_STEP_BACK, ReviewItem, due_items


def test_a_miss_is_scheduled_soon():
    item = ReviewItem.first_miss("cash_6max_100bb_BTN_RFI", "J3o", hands_played=10)
    assert item.streak == 0
    assert item.due_at == 10 + INTERVALS[0]


def test_correct_answers_push_the_interval_out():
    item = ReviewItem.first_miss("chart", "AA", hands_played=0)
    intervals = []
    played = 0
    for _ in range(len(INTERVALS)):
        played = item.due_at
        item = item.next_after(correct=True, hands_played=played)
        intervals.append(item.due_at - played)
    assert intervals == sorted(intervals), "intervals must grow, never shrink"
    assert intervals[-1] == INTERVALS[-1]


def test_a_lapse_steps_back_but_not_to_zero():
    item = ReviewItem("chart", "AA", streak=4, due_at=0)
    lapsed = item.next_after(correct=False, hands_played=100)
    assert lapsed.streak == 4 - LAPSE_STEP_BACK
    assert lapsed.due_at == 100 + INTERVALS[lapsed.streak]


def test_repeated_lapses_bottom_out_at_the_shortest_interval():
    item = ReviewItem("chart", "AA", streak=1, due_at=0)
    for _ in range(5):
        item = item.next_after(correct=False, hands_played=0)
    assert item.streak == 0
    assert item.due_at == INTERVALS[0]


def test_an_item_retires_once_it_is_known():
    item = ReviewItem("chart", "AA", streak=len(INTERVALS) - 1, due_at=0)
    assert item.is_retired()
    assert not ReviewItem("chart", "AA", streak=0, due_at=0).is_retired()


def test_due_depends_on_hands_played():
    item = ReviewItem("chart", "AA", streak=0, due_at=20)
    assert not item.is_due(19)
    assert item.is_due(20)
    assert item.is_due(50)


def test_due_items_are_ordered_most_overdue_first():
    items = [
        ReviewItem("chart", "AA", due_at=30),
        ReviewItem("chart", "KK", due_at=5),
        ReviewItem("chart", "QQ", due_at=18),
        ReviewItem("chart", "JJ", due_at=999),
    ]
    order = [item.hand for item in due_items(items, hands_played=40)]
    assert order == ["KK", "QQ", "AA"]
    assert "JJ" not in order


def test_a_spot_answered_right_first_time_is_never_tracked():
    """Only mistakes enter the queue; see StatisticsManagerDB._reschedule."""
    assert ReviewItem.first_miss("chart", "AA", 0).streak == 0

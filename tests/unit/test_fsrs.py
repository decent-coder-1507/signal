from datetime import UTC, datetime, timedelta

import pytest

from signal_core.gym.fsrs import (
    CardState,
    W,
    init_difficulty,
    next_interval,
    retrievability,
    review,
)

T0 = datetime(2026, 11, 7, 9, 0, tzinfo=UTC)


def test_retrievability_is_90_percent_at_stability() -> None:
    assert retrievability(10, 10) == pytest.approx(0.9, abs=1e-9)
    assert retrievability(0, 10) == 1.0
    assert next_interval(10.0) == 10  # at 90% desired retention the interval equals the stability


@pytest.mark.parametrize(("rating", "days"), [(1, 1), (2, round(W[1])), (3, round(W[2])), (4, round(W[3]))])
def test_first_review_intervals_follow_initial_stability(rating: int, days: int) -> None:
    s, due = review(CardState(), rating, T0)
    assert due == T0 + timedelta(days=max(days, 1))
    assert s.stability == pytest.approx(max(W[rating - 1], 0.1))
    assert s.difficulty == pytest.approx(init_difficulty(rating))
    assert s.reps == 1 and s.state == ("relearning" if rating == 1 else "review")


def test_good_reviews_grow_the_interval_monotonically() -> None:
    s, due = review(CardState(), 3, T0)
    intervals = [(due - T0).days]
    now = due
    for _ in range(4):
        s, nxt = review(s, 3, now)
        intervals.append((nxt - now).days)
        now = nxt
    assert intervals == sorted(intervals) and intervals[-1] > intervals[0] * 5


def test_again_after_review_resets_and_counts_lapse() -> None:
    s, due = review(CardState(), 3, T0)
    s2, due2 = review(s, 3, due)
    s3, due3 = review(s2, 1, due2)
    assert s3.lapses == 1 and s3.stability < s2.stability and due3 == due2 + timedelta(days=1)
    assert s3.difficulty > s2.difficulty  # lapses make the card harder


def test_easy_beats_good_beats_hard_and_difficulty_bounds() -> None:
    s, due = review(CardState(), 3, T0)
    outs = {g: review(s, g, due) for g in (2, 3, 4)}
    assert outs[2][0].stability < outs[3][0].stability < outs[4][0].stability
    hard = CardState()
    for _ in range(20):
        hard, _ = review(hard, 1, T0)
    assert 1.0 <= hard.difficulty <= 10.0


def test_reviewing_late_gives_more_stability_than_early() -> None:
    s, due = review(CardState(), 3, T0)
    early, _ = review(s, 3, T0 + timedelta(days=1))
    late, _ = review(s, 3, due + timedelta(days=5))
    assert late.stability > early.stability


def test_invalid_rating() -> None:
    with pytest.raises(ValueError):
        review(CardState(), 5, T0)

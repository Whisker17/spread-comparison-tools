"""Canonical walk-the-book vectors from WHI-799 §4.7."""

from decimal import Decimal

from spread_compare.bookwalk import walk_book

# mid = 100_000, N = 10_000 → q_star = 0.1 BTC
Q_STAR = Decimal("0.1")

ASKS = [
    (Decimal("100010"), Decimal("0.04")),
    (Decimal("100050"), Decimal("0.04")),
    (Decimal("100100"), Decimal("0.10")),
]
BIDS = [
    (Decimal("99990"), Decimal("0.04")),
    (Decimal("99950"), Decimal("0.04")),
    (Decimal("99900"), Decimal("0.10")),
]


def test_walk_book_buy_fixture_p_star() -> None:
    p_star = walk_book(ASKS, Q_STAR)
    assert p_star == Decimal("100044")


def test_walk_book_sell_fixture_p_star() -> None:
    p_star = walk_book(BIDS, Q_STAR)
    assert p_star == Decimal("99956")


def test_walk_book_insufficient_depth_returns_none() -> None:
    shallow = [(Decimal("100010"), Decimal("0.01"))]
    assert walk_book(shallow, Q_STAR) is None


def test_walk_book_negative_size_raises() -> None:
    import pytest

    with pytest.raises(ValueError, match="non-negative"):
        walk_book([(Decimal("100010"), Decimal("-0.01"))], Q_STAR)

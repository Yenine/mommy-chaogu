"""Market-local date conversion stays consistent across user-facing consumers."""

from __future__ import annotations

from datetime import UTC, datetime

from mommy_chaogu.market_data.time_utils import market_trade_date


def test_beijing_handles_a_share_and_board_midnight_utc() -> None:
    timestamp = datetime(2026, 7, 1, 16, tzinfo=UTC)

    assert market_trade_date(timestamp, "600519") == "2026-07-02"
    assert market_trade_date(timestamp, "sh000001") == "2026-07-02"
    assert market_trade_date(timestamp, "BK1036") == "2026-07-02"


def test_us_symbols_and_indices_use_new_york() -> None:
    timestamp = datetime(2026, 7, 1, 0, 30, tzinfo=UTC)

    assert market_trade_date(timestamp, "AAPL") == "2026-06-30"
    assert market_trade_date(timestamp, "^GSPC") == "2026-06-30"
    assert market_trade_date(timestamp, "SHW") == "2026-06-30"
    assert market_trade_date(timestamp, "BK") == "2026-06-30"


def test_naive_timestamp_preserves_legacy_wall_date() -> None:
    assert market_trade_date(datetime(2026, 7, 2, 9, 30), "600519") == "2026-07-02"

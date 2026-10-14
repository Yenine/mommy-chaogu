"""Market-local date conversion stays consistent across user-facing consumers."""

from __future__ import annotations

from datetime import UTC, date, datetime

from mommy_chaogu.market_data.time_utils import (
    TZ_BEIJING,
    beijing_trade_date,
    is_a_share_trading_day,
    market_trade_date,
)


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


# ---------- P1：单一真相源常量与北京交易日助手 ----------


def test_tz_beijing_is_the_public_singleton_constant() -> None:
    """公开常量即 Asia/Shanghai 实例（各模块从 time_utils 导入同一对象）。"""
    assert TZ_BEIJING.key == "Asia/Shanghai"


def test_beijing_trade_date_converts_aware_and_naive() -> None:
    # aware UTC：北京午夜（UTC 前一天 16:00）必须落到北京次日
    assert beijing_trade_date(datetime(2026, 7, 1, 16, tzinfo=UTC)) == "2026-07-02"
    # aware UTC：北京周一零点（UTC 周日 16:00）必须落到周一
    assert beijing_trade_date(datetime(2026, 7, 5, 16, tzinfo=UTC)) == "2026-07-06"
    # naive：防御性按北京墙时间解释，日期不变
    assert beijing_trade_date(datetime(2026, 7, 2, 9, 30)) == "2026-07-02"
    # aware 北京时间：原样
    assert beijing_trade_date(datetime(2026, 7, 2, 15, tzinfo=TZ_BEIJING)) == "2026-07-02"


# ---------- P1：A 股交易日谓词 ----------


def test_trading_day_predicate_true_when_date_observed() -> None:
    known = {date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 6)}
    assert is_a_share_trading_day(date(2026, 7, 3), known) is True


def test_trading_day_predicate_false_for_absence_inside_span() -> None:
    """跨度内缺席 = 非交易日（周末/节假日），前提是集合来自指数/板块日 K。"""
    known = {date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 6)}
    assert is_a_share_trading_day(date(2026, 7, 4), known) is False  # 周六
    assert is_a_share_trading_day(date(2026, 7, 5), known) is False  # 周日


def test_trading_day_predicate_unknown_outside_span_or_empty() -> None:
    known = {date(2026, 7, 2), date(2026, 7, 3)}
    assert is_a_share_trading_day(date(2026, 7, 1), known) is None  # 跨度之前
    assert is_a_share_trading_day(date(2026, 7, 4), known) is None  # 跨度之后
    assert is_a_share_trading_day(date(2026, 7, 2), set()) is None  # 无数据
    # 单日集合对其他日期一律未知（一个观测点证明不了跨度）
    assert is_a_share_trading_day(date(2026, 7, 3), {date(2026, 7, 2)}) is None

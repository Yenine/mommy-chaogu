"""Focused bars-card acceptance tests for market date and data caveats."""

from __future__ import annotations

from mommy_chaogu.tui.widgets.cards import _bar_trade_date, bars_card, flows_command_card


def _bar(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "code": "BK1036",
        "name": "板块",
        "timestamp": "2026-07-01T16:00:00+00:00",
        "close": "100",
        "change_pct": "1",
        "volume": 100,
        "adjustment": "forward",
        "currency": "CNY",
    }
    row.update(overrides)
    return row


def test_bars_card_prefers_market_trade_date_and_shows_stale_warning() -> None:
    card = bars_card([_bar(data_source="stale_cache")])
    rendered = str(card.render())

    assert "2026-07-02" in rendered
    assert "拉新失败" in rendered
    assert "复权口径" in rendered
    assert "成交额币种" in rendered


def test_bars_card_reuses_new_york_for_us_fallback_timestamp() -> None:
    row = _bar(code="AAPL", trade_date=None)
    assert _bar_trade_date(row) == "2026-07-01"

    row["timestamp"] = "2026-07-01T00:30:00+00:00"
    assert _bar_trade_date(row) == "2026-06-30"


def test_flows_command_card_labels_stale_today_with_data_date() -> None:
    """/flows 卡「今日」行遵守数据日期契约（P3）：跨日缓存不当今日。"""
    from decimal import Decimal

    from mommy_chaogu.flows.service import FlowSummary

    today = FlowSummary(
        code="600519",
        name="茅台",
        main_net=Decimal("50000000"),
        super_large_net=Decimal("0"),
        large_net=Decimal("0"),
        medium_net=Decimal("0"),
        small_net=Decimal("0"),
        main_net_ratio=None,
        data_date="2026-10-12",
    )

    # 跨交易日缓存：标签带数据日期，不再是裸「今日」
    stale = flows_command_card(
        "600519",
        {"today": today, "today_data_date": "2026-10-12", "today_is_current": False},
    )
    rendered = str(stale.render())
    assert "缓存(数据日期 2026-10-12)  主力" in rendered
    assert "今日  主力" not in rendered

    # 日期未知（旧库迁移前 NULL 行）：同样不当今日
    unknown = flows_command_card(
        "600519", {"today": today, "today_data_date": "", "today_is_current": False}
    )
    assert "缓存(数据日期 未知)" in str(unknown.render())

    # 当日缓存：标签照旧「今日」
    current = flows_command_card(
        "600519",
        {"today": today, "today_data_date": "2026-10-12", "today_is_current": True},
    )
    assert "今日  主力" in str(current.render())

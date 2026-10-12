"""Focused bars-card acceptance tests for market date and data caveats."""

from __future__ import annotations

from mommy_chaogu.tui.widgets.cards import _bar_trade_date, bars_card


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

"""P1 根因测试：bar_cache 日线落键按北京交易日 + 历史脏键读侧容错。

根因（cache/store.backfill_history 日线分支）：aware UTC 时间戳直接
strftime 会把北京交易日落成前一个自然日——北京 07-02 的日线落 07-01 键、
周一 bar 落周日键、节后首日 bar 落假期最后一日键。修复后落键一律按
``market_data/time_utils.beijing_trade_date``（与分钟分支、cache/adapter
的落键语义对齐）。

历史脏键只做读侧容错（不迁移、不改写任何既有行）：get_bars 按 bar_json
内 timestamp 反推真实交易日做区间过滤/排序/去重（同 timestamp 多行并存
时 fetched_at 新者胜出）；set_minute_bars 的合并判断按真实交易日匹配，
使同日早段不被错误行键隔断。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from mommy_chaogu.cache.store import CacheStore
from mommy_chaogu.market_data.types import AdjustmentType, Bar, BarInterval, Money

CODE = "600519"
ADJ = AdjustmentType.FORWARD


def _d1_bar(ts: datetime, close: str = "100.00") -> Bar:
    return Bar(
        code=CODE,
        name="贵州茅台",
        interval=BarInterval.D1,
        adjustment=ADJ,
        timestamp=ts,
        open=Decimal("100.00"),
        high=Decimal(close),
        low=Decimal("99.00"),
        close=Decimal(close),
        volume=1000,
        turnover=Money.from_yuan(100_000),
    )


def _fake_adapter(bars: list[Bar]) -> MagicMock:
    adapter = MagicMock()
    adapter.get_bars.return_value = bars
    adapter.get_history_money_flow.return_value = []
    return adapter


@pytest.fixture
def store(tmp_path: Path) -> CacheStore:
    return CacheStore(tmp_path / "test.db")


def _row_keys(store: CacheStore) -> list[tuple[str, str]]:
    with store.session() as s:
        return [
            (str(row[0]), str(row[1]))
            for row in s.execute(
                text("SELECT trade_date, bar_json FROM bar_cache ORDER BY trade_date")
            ).all()
        ]


# ---------- 根因：日线落键按北京交易日 ----------


def test_backfill_daily_bar_crosses_utc_midnight_keys_beijing_day(store: CacheStore) -> None:
    """北京 07-02 的日线（UTC 07-01 16:00）必须落 07-02 键，不是 07-01。"""
    result = store.backfill_history(
        _fake_adapter([_d1_bar(datetime(2026, 7, 1, 16, tzinfo=UTC))]), CODE
    )

    assert result["bars_written"] == 1
    assert result["errors"] == []
    assert [key for key, _ in _row_keys(store)] == ["2026-07-02"]
    rows = store.get_bars(CODE, "1d", "forward", "2026-07-02", "2026-07-02")
    assert rows is not None and len(rows) == 1


def test_backfill_daily_monday_bar_keys_monday_not_sunday(store: CacheStore) -> None:
    """北京周一 2026-07-06 的日线（UTC 周日 16:00）必须落周一键，不是周日键。"""
    store.backfill_history(_fake_adapter([_d1_bar(datetime(2026, 7, 5, 16, tzinfo=UTC))]), CODE)

    assert [key for key, _ in _row_keys(store)] == ["2026-07-06"]


def test_backfill_daily_post_holiday_first_day_keys_real_trade_date(store: CacheStore) -> None:
    """节后首日：国庆假期后首个交易日北京 10-09（UTC 10-08 16:00）落 10-09 键。"""
    store.backfill_history(_fake_adapter([_d1_bar(datetime(2026, 10, 8, 16, tzinfo=UTC))]), CODE)

    assert [key for key, _ in _row_keys(store)] == ["2026-10-09"]


def test_backfill_daily_naive_timestamp_keeps_wall_date(store: CacheStore) -> None:
    """naive 时间戳防御性按北京墙时间解释（与缓存层历史语义一致）。"""
    store.backfill_history(_fake_adapter([_d1_bar(datetime(2026, 6, 1, 15, 0))]), CODE)

    assert [key for key, _ in _row_keys(store)] == ["2026-06-01"]


# ---------- 读侧容错：历史脏键不迁移、不改写，读取按真实交易日 ----------


def _insert_row(
    store: CacheStore, key: str, bar_json: str, fetched_at: datetime, interval: str = "1d"
) -> None:
    with store.session() as s:
        s.execute(
            text("""
                INSERT INTO bar_cache (code, interval, adj_type, trade_date, bar_json, fetched_at)
                VALUES (:c, :i, :a, :d, :j, :f)
            """),
            {"c": CODE, "i": interval, "a": "forward", "d": key, "j": bar_json, "f": fetched_at},
        )


def _bar_json(ts: datetime, close: str) -> str:
    return json.dumps(
        {
            "code": CODE,
            "name": "贵州茅台",
            "timestamp": ts.isoformat(),
            "interval": "1d",
            "adjustment": "forward",
            "open": "100.00",
            "high": "101.00",
            "low": "99.00",
            "close": close,
            "volume": 1000,
            "turnover": "100000",
        }
    )


def test_dirty_daily_row_included_by_real_date_range_filter(store: CacheStore) -> None:
    """脏键行（键 07-01、真实交易日 07-02）在 07-02 区间读取时必须可见。

    修复前的读侧按行键过滤会把它整行丢弃——用户看不到已缓存的数据。
    """
    # 脏行：键 = UTC strftime（07-01），bar 真实北京交易日 07-02
    _insert_row(
        store,
        "2026-07-01",
        _bar_json(datetime(2026, 7, 1, 16, tzinfo=UTC), "100.00"),
        datetime(2026, 7, 1, tzinfo=UTC),
    )

    rows = store.get_bars(CODE, "1d", "forward", "2026-07-02", "2026-07-02")
    assert rows is not None
    assert len(rows) == 1
    assert rows[0]["close"] == "100.00"


def test_dirty_and_clean_rows_dedup_with_freshest_wins(store: CacheStore) -> None:
    """脏键行与修复后正确键行并存：同 timestamp 只回一份，fetched_at 新者胜出。"""
    ts = datetime(2026, 7, 1, 16, tzinfo=UTC)  # 北京 07-02
    _insert_row(store, "2026-07-01", _bar_json(ts, "100.00"), datetime(2026, 7, 1, tzinfo=UTC))

    # 修复后的回填：同一根 bar 的新值落正确键 07-02
    store.backfill_history(_fake_adapter([_d1_bar(ts, close="105.00")]), CODE)

    rows = store.get_bars(CODE, "1d", "forward")
    assert rows is not None
    assert len(rows) == 1  # 不因脏键行重复
    assert rows[0]["close"] == "105.00"  # 新值胜出
    # 脏行原样保留（不迁移、不改写）
    assert [key for key, _ in _row_keys(store)] == ["2026-07-01", "2026-07-02"]


def test_read_orders_by_timestamp_not_dirty_key(store: CacheStore) -> None:
    """脏键行排序按 bar timestamp（真实时间序），不按错误行键。"""
    _insert_row(
        store,
        "2026-07-01",
        _bar_json(datetime(2026, 7, 1, 16, tzinfo=UTC), "100.00"),
        datetime(2026, 7, 1, tzinfo=UTC),
    )
    _insert_row(
        store,
        "2026-07-03",
        _bar_json(datetime(2026, 7, 3, 15, tzinfo=UTC), "101.00"),
        datetime(2026, 7, 3, tzinfo=UTC),
    )

    rows = store.get_bars(CODE, "1d", "forward")
    assert rows is not None
    assert [r["timestamp"] for r in rows] == sorted(r["timestamp"] for r in rows)


# ---------- 合并判断容错：分钟打包按真实交易日合并 ----------


def _minute_bar_dict(ts: datetime, close: str) -> dict[str, Any]:
    return {
        "code": CODE,
        "name": "贵州茅台",
        "timestamp": ts.isoformat(),
        "interval": "5m",
        "adjustment": "forward",
        "open": "100.00",
        "high": "101.00",
        "low": "99.00",
        "close": close,
        "volume": 1000,
        "turnover": "100000",
    }


def test_minute_merge_picks_up_dirty_keyed_early_segment(store: CacheStore) -> None:
    """脏键分钟打包行的早段并入正确键，部分日写入仍不丢段。"""
    early_ts = datetime(2026, 9, 29, 1, 30, tzinfo=UTC)  # 北京 09-29 09:30
    late_ts = early_ts + timedelta(minutes=5)
    # 历史脏行：键 09-28（UTC strftime 早一天），bar 真实交易日 09-29
    _insert_row(
        store,
        "2026-09-28",
        json.dumps([_minute_bar_dict(early_ts, "10.00")]),
        datetime(2026, 9, 28, tzinfo=UTC),
        interval="5m",
    )

    # 修复后的部分日写入：真实交易日 09-29 的尾段
    store.set_minute_bars(CODE, "5m", "forward", "2026-09-29", [_minute_bar_dict(late_ts, "10.01")])

    rows = store.get_bars(CODE, "5m", "forward")
    assert rows is not None
    assert [r["close"] for r in rows] == ["10.00", "10.01"]  # 早段 + 尾段，各一份
    # 脏行不迁移、不改写；正确键行包含合并后的整段
    keys = {key: json.loads(bar_json) for key, bar_json in _row_keys(store)}
    assert set(keys) == {"2026-09-28", "2026-09-29"}
    assert [b["close"] for b in keys["2026-09-29"]] == ["10.00", "10.01"]


def test_minute_pack_from_other_real_dates_not_merged(store: CacheStore) -> None:
    """合并只认真实交易日：别的交易日的打包行不会被并进来。"""
    other_day_ts = datetime(2026, 9, 28, 1, 30, tzinfo=UTC)  # 北京 09-28
    _insert_row(
        store,
        "2026-09-28",
        json.dumps([_minute_bar_dict(other_day_ts, "9.99")]),
        datetime(2026, 9, 28, tzinfo=UTC),
        interval="5m",
    )

    store.set_minute_bars(
        CODE,
        "5m",
        "forward",
        "2026-09-29",
        [_minute_bar_dict(datetime(2026, 9, 29, 1, 30, tzinfo=UTC), "10.00")],
    )

    rows = store.get_bars(CODE, "5m", "forward")
    assert rows is not None
    assert [r["close"] for r in rows] == ["9.99", "10.00"]  # 两日各归各行，不混入
    keys = {key: json.loads(bar_json) for key, bar_json in _row_keys(store)}
    assert [b["close"] for b in keys["2026-09-29"]] == ["10.00"]

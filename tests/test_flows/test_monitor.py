"""flows.monitor 单测 — 状态持久化的跨交易日契约（P3）。

跨交易日（含 saved_at 缺失/不可解析 → 无法证明同日）的 last_ratios 直接
丢弃：长假后首轮的隔夜差是跨日变化，不是 5 分钟异动。evaluate 拿到空
prev 时 delta 规则不触发，首轮只建基线，不产生假信号。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from mommy_chaogu.cache import CacheStore
from mommy_chaogu.flows.monitor import FlowMonitor
from mommy_chaogu.flows.pool import CustomPool
from mommy_chaogu.flows.service import FlowService


class FakeAdapter:
    """最小 adapter：tick 轮询不在本文件范围，仅满足 FlowService 构造。"""

    def get_quote(self, code: str) -> Any:
        return None

    def get_today_money_flow(self, code: str) -> list[Any]:
        return []

    def get_history_money_flow(self, code: str, days: int = 30) -> list[Any]:
        return []


def _monitor(tmp_path: Path) -> FlowMonitor:
    store = CacheStore(tmp_path / "monitor.db")
    service = FlowService(FakeAdapter(), store)
    return FlowMonitor(CustomPool([]), service, state_path=tmp_path / "state.json")


def _write_state(path: Path, saved_at: str | None, ratios: dict[str, str]) -> None:
    data: dict[str, Any] = {"last_ratios": ratios}
    if saved_at is not None:
        data["saved_at"] = saved_at
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_load_state_same_trade_date_kept(tmp_path: Path) -> None:
    """同交易日 state：last_ratios 恢复（正常重启续跑）。"""
    m = _monitor(tmp_path)
    assert m.state_path is not None
    saved_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    _write_state(m.state_path, saved_at, {"600519": "0.0005"})
    m._load_state()
    assert m._last_ratios == {"600519": Decimal("0.0005")}


def test_load_state_cross_trade_date_discarded(tmp_path: Path) -> None:
    """跨交易日（长假后重启）：last_ratios 丢弃，首轮只建基线。"""
    m = _monitor(tmp_path)
    assert m.state_path is not None
    saved_at = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    _write_state(m.state_path, saved_at, {"600519": "0.0005"})
    m._load_state()
    assert m._last_ratios == {}


def test_load_state_missing_saved_at_discarded(tmp_path: Path) -> None:
    """saved_at 缺失 → 无法证明同交易日，按跨日处理。"""
    m = _monitor(tmp_path)
    assert m.state_path is not None
    _write_state(m.state_path, None, {"600519": "0.0005"})
    m._load_state()
    assert m._last_ratios == {}


def test_load_state_bad_saved_at_discarded(tmp_path: Path) -> None:
    """saved_at 不可解析：丢弃，不崩。"""
    m = _monitor(tmp_path)
    assert m.state_path is not None
    _write_state(m.state_path, "not-a-date", {"600519": "0.0005"})
    m._load_state()
    assert m._last_ratios == {}


def test_load_state_corrupt_json_discarded(tmp_path: Path) -> None:
    """坏 JSON：维持旧行为（warning + 空 state）。"""
    m = _monitor(tmp_path)
    assert m.state_path is not None
    m.state_path.write_text("{oops", encoding="utf-8")
    m._load_state()
    assert m._last_ratios == {}


def test_load_state_no_file_noop(tmp_path: Path) -> None:
    """无 state 文件：空 state 起步。"""
    m = _monitor(tmp_path)
    m._load_state()
    assert m._last_ratios == {}

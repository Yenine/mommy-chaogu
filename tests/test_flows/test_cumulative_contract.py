"""跨域数值口径契约测试（P5）。

同一交易日多条资金流记录时，「每日累计取末条」必须三层一致：
flows 域函数（flows/cumulative）、回测引擎（backtest/engine）与 web
展示层（web/routes/quotes）都取末条——历史上 backtest 取首条，与实盘
口径系统性不一致。

另含阈值哨兵：backtest ``SPIKE_THRESHOLD`` 与 flows/signals
``flow_in_spike`` 的 5bp 数值有意对齐（度量不同、刻意不 import 耦合），
哨兵断言两侧相等，改阈值时必须双侧同步。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from mommy_chaogu.backtest.engine import SPIKE_THRESHOLD, BacktestEngine
from mommy_chaogu.cache.store import CacheStore
from mommy_chaogu.flows.cumulative import latest_flow_row, latest_money_flow
from mommy_chaogu.flows.signals import default_rules
from mommy_chaogu.market_data import MarketType, Money, MoneyFlow, Quote, QuoteType
from mommy_chaogu.web.routes.quotes import get_today_money_flow

TRADE_DATE = "2026-06-01"
CODE = "600519"
FLOAT_MCAP = 10_000_000_000  # 100 亿流通市值


def _flow(ts_hour: int, main_net: int) -> MoneyFlow:
    return MoneyFlow(
        code=CODE,
        name="测试股",
        timestamp=datetime(2026, 6, 1, ts_hour, 0, tzinfo=UTC),
        main_net=Money.from_yuan(main_net),
        small_net=Money.from_yuan(0),
        medium_net=Money.from_yuan(0),
        large_net=Money.from_yuan(0),
        super_large_net=Money.from_yuan(0),
        main_net_ratio=Decimal("1.0"),
    )


def _flow_dict(ts_hour: int, main_net: int) -> dict[str, Any]:
    """与 CacheStore.set_money_flow_history 存储形态一致的 dict 行。"""
    return {
        "code": CODE,
        "name": "测试股",
        "timestamp": f"2026-06-01T{ts_hour:02d}:00:00+00:00",
        "main_net": {"amount": str(main_net), "currency": "CNY"},
        "small_net": {"amount": "0", "currency": "CNY"},
        "medium_net": {"amount": "0", "currency": "CNY"},
        "large_net": {"amount": "0", "currency": "CNY"},
        "super_large_net": {"amount": "0", "currency": "CNY"},
        "main_net_ratio": "1.0",
    }


# 同一交易日的多条累计记录：前两条是阈下旧快照，末条是收盘最新累计。
# 旧回测实现取首条（1bp < 5bp 不触发）——若回退会直接暴露为断言失败。
FLOWS = [_flow(1, 1_000_000), _flow(7, 2_000_000), _flow(15, 500_000_000)]
FLOW_DICTS = [_flow_dict(1, 1_000_000), _flow_dict(7, 2_000_000), _flow_dict(15, 500_000_000)]
LAST_MAIN_NET = 500_000_000


def _make_quote(code: str) -> Quote:
    return Quote(
        code=code,
        name="测试股",
        market=MarketType.SH,
        quote_type=QuoteType.STOCK,
        price=Decimal("10"),
        open=Decimal("10"),
        high=Decimal("10"),
        low=Decimal("10"),
        prev_close=Decimal("10"),
        change=Decimal("0"),
        change_pct=Decimal("0"),
        volume=0,
        turnover=Money.from_yuan(0),
        turnover_rate=None,
        volume_ratio=None,
        pe_dynamic=None,
        total_market_cap=Money.from_yuan(FLOAT_MCAP),
        circulating_market_cap=Money.from_yuan(FLOAT_MCAP),
        timestamp=datetime.now(UTC),
    )


def _make_bar(code: str, date: str, close: str) -> dict[str, Any]:
    return {
        "code": code,
        "name": "测试股",
        "timestamp": f"{date}T15:00:00+08:00",
        "interval": "1d",
        "adjustment": "forward",
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1_000_000,
        "turnover": "10000000.00",
        "change_pct": "1.0",
        "turnover_rate": "1.0",
        "amplitude": "2.0",
    }


class _StubFlowAdapter:
    """只实现 get_today_money_flow 的路由测试桩。"""

    def __init__(self, flows: list[MoneyFlow]) -> None:
        self._flows = flows

    def get_today_money_flow(self, code: str) -> list[MoneyFlow]:
        return self._flows


# ---------------------------------------------------------------------------
# 跨层一致性：三处取值都是末条
# ---------------------------------------------------------------------------


def test_flows_domain_function_takes_last_record() -> None:
    """flows 域函数：MoneyFlow 适配与 dict 行核心都取末条，空序列返回 None。"""
    assert latest_money_flow(FLOWS) is FLOWS[-1]
    assert latest_money_flow([]) is None
    assert latest_flow_row(FLOW_DICTS) == FLOW_DICTS[-1]
    assert latest_flow_row([]) is None


def test_web_route_cumulative_takes_last_record() -> None:
    """web/routes/quotes：当日累计 = 序列末条（与 flows 域同一口径）。"""
    resp = get_today_money_flow(CODE, _StubFlowAdapter(FLOWS))  # type: ignore[arg-type]
    assert resp.cumulative.main_net == Decimal(LAST_MAIN_NET)
    assert resp.items[-1].main_net == Decimal(LAST_MAIN_NET)


def test_backtest_engine_takes_last_record(tmp_path: Path) -> None:
    """backtest/engine：同日多条记录取末条（首条阈下，末条阈上）。"""
    store = CacheStore(tmp_path / "market.db")
    store.set_quote(CODE, _make_quote(CODE))
    store.set_bar(CODE, "1d", "forward", TRADE_DATE, _make_bar(CODE, TRADE_DATE, "10"))
    store.set_money_flow_history(CODE, TRADE_DATE, FLOW_DICTS)

    engine = BacktestEngine(tmp_path / "market.db")

    # 直接验证加载口径：flow_by_date 用末条 main_net
    loaded = engine._load_code_data(CODE, TRADE_DATE, TRADE_DATE)
    assert loaded is not None
    assert loaded["flow_by_date"][TRADE_DATE] == Decimal(str(LAST_MAIN_NET))

    # 端到端：末条 5 亿 → ratio 500bp > 5bp 触发且 main_net_yi=5.0；
    # 旧实现（取首条 1 亿 = 1bp）不会触发任何信号
    result = engine.run([CODE], TRADE_DATE, TRADE_DATE, hold_days=1, costs=None)
    assert result.total_signals == 1
    assert result.signals_detail[0]["main_net_yi"] == LAST_MAIN_NET / 100_000_000


# ---------------------------------------------------------------------------
# 阈值哨兵：数值有意对齐、度量不同
# ---------------------------------------------------------------------------


def test_spike_threshold_sentinel() -> None:
    """backtest SPIKE_THRESHOLD 与 signals flow_in_spike 数值必须相等。

    两侧度量不同（日累计 ratio vs 5min delta ratio）、刻意不 import 耦合，
    但数值有意对齐在 5bp——调整任何一侧都必须同步另一侧（双侧注释同款声明）。
    """
    rule = next(r for r in default_rules() if r.rule_id == "flow_in_spike")
    assert Decimal("0.0005") == SPIKE_THRESHOLD
    assert rule.threshold_bp == Decimal("5")
    assert SPIKE_THRESHOLD * Decimal("10000") == rule.threshold_bp

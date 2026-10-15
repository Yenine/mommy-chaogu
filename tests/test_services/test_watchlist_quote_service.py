"""WatchlistQuoteService：批量报价 + 资金流 join 的统一实现。"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from mommy_chaogu.services.watchlist_quote_service import WatchlistQuoteService


def _flow(main_net_yuan: str) -> Any:
    return SimpleNamespace(main_net=SimpleNamespace(amount=Decimal(main_net_yuan), currency="CNY"))


class FakeAdapter:
    """duck-typed adapter：预设报价与资金流，可注入失败。"""

    def __init__(
        self,
        quotes: dict[str, Any] | None = None,
        flows: dict[str, Any] | None = None,
        quotes_raise: bool = False,
        flow_fail_codes: set[str] | None = None,
    ) -> None:
        self._quotes = quotes or {}
        self._flows = flows or {}
        self._quotes_raise = quotes_raise
        self._flow_fail = flow_fail_codes or set()

    def get_quotes(self, codes: list[str]) -> list[Any]:
        if self._quotes_raise:
            raise RuntimeError("上游不可用")
        return [self._quotes[c] for c in codes if c in self._quotes]

    def get_today_money_flow(self, code: str) -> list[Any]:
        if code in self._flow_fail:
            raise RuntimeError("单只资金流失败")
        if code in self._flows:
            return [self._flows[code]]
        return []

    def format_source_label(self) -> str:
        return "腾讯 实时"


def _quote(code: str, name: str, price: str, change_pct: str) -> Any:
    return SimpleNamespace(
        code=code,
        name=name,
        price=Decimal(price),
        change_pct=Decimal(change_pct),
        change=Decimal("0.5"),
    )


def test_fetch_joins_quotes_and_flows_in_order() -> None:
    adapter = FakeAdapter(
        quotes={
            "600519": _quote("600519", "贵州茅台", "1500", "1.2"),
            "000001": _quote("000001", "平安银行", "10", "-0.5"),
        },
        flows={"600519": _flow("300000000")},
    )
    rows = WatchlistQuoteService(adapter).fetch(["600519", "000001"])
    assert [r["code"] for r in rows] == ["600519", "000001"]  # 顺序保持
    assert rows[0]["name"] == "贵州茅台"
    assert rows[0]["price"] == Decimal("1500")
    assert rows[0]["main_flow"] is not None and rows[0]["main_flow"].amount == Decimal("300000000")
    assert rows[1]["main_flow"] is None  # 无资金流数据 → None 而不是报错
    assert "quote_unavailable" not in rows[0]


def test_fetch_records_source_label() -> None:
    svc = WatchlistQuoteService(FakeAdapter(quotes={"600519": _quote("600519", "茅", "1", "0")}))
    svc.fetch(["600519"])
    assert svc.last_source_label == "腾讯 实时"


class FakeCachedAdapter(FakeAdapter):
    """模拟 CachedMarketDataAdapter 的共享来源字段行为。

    get_today_money_flow 像真实缓存装饰器一样改写 ``last_source`` 并写
    ``last_source_trade_date``（报价路径从不写后者——跨轮残留的来源）。
    """

    def __init__(self, quotes: dict[str, Any] | None = None) -> None:
        super().__init__(quotes=quotes)
        self.last_source = "network"
        self.last_source_trade_date = ""

    def get_quotes(self, codes: list[str]) -> list[Any]:
        # 像真实装饰器：本次读取决定来源字段（成功拉到 → network）
        self.last_source = "network"
        return super().get_quotes(codes)

    def get_today_money_flow(self, code: str) -> list[Any]:
        self.last_source = "cache"
        self.last_source_trade_date = "2026-10-13"
        return super().get_today_money_flow(code)

    def source_snapshot(self) -> tuple[str, str]:
        return (self.last_source, self.last_source_trade_date)

    def format_source_label_from(self, source: str, trade_date: str) -> str:
        if not source:
            return ""
        return f"{source}｜数据日期 {trade_date}" if trade_date else source


def test_source_label_snapshots_quote_source_not_flow() -> None:
    """报价标签取 get_quotes 返回瞬间的快照。

    回归：资金流线程池改写共享 last_source 后，标签不再张冠李戴成资金流
    来源；quote 路径从不产生数据日期，第二轮 fetch 也不会把上一轮资金流
    残留的 last_source_trade_date 拼成「数据日期」后缀。
    """
    adapter = FakeCachedAdapter(quotes={"600519": _quote("600519", "茅", "1", "0")})
    svc = WatchlistQuoteService(adapter)
    svc.fetch(["600519"])
    assert svc.last_source_label == "network"
    # adapter 共享字段已被资金流改写（模拟真实装饰器行为）
    assert adapter.last_source == "cache"
    assert adapter.last_source_trade_date == "2026-10-13"
    # 第二轮：残留的 trade_date 不进报价标签
    svc.fetch(["600519"])
    assert svc.last_source_label == "network"


def test_source_label_cleared_when_batch_quote_raises() -> None:
    """批量报价抛异常（缓存装饰器自身故障）时标签清空，不沿用残留状态。"""

    class RaisingSnapshotAdapter(FakeCachedAdapter):
        def get_quotes(self, codes: list[str]) -> list[Any]:
            raise RuntimeError("store 读失败")

    svc = WatchlistQuoteService(RaisingSnapshotAdapter())
    svc.fetch(["600519"])
    assert svc.last_source_label == ""


def test_batch_quote_failure_returns_placeholder_rows() -> None:
    """批量报价整体失败 → 每个 code 一条占位行，资金流照常 join。"""
    adapter = FakeAdapter(quotes_raise=True, flows={"600519": _flow("-50000000")})
    rows = WatchlistQuoteService(adapter).fetch(["600519", "000001"])
    assert len(rows) == 2
    assert all(r.get("quote_unavailable") is True for r in rows)
    assert rows[0]["price"] is None
    assert rows[0]["main_flow"] is not None and rows[0]["main_flow"].amount == Decimal("-50000000")
    assert rows[1]["main_flow"] is None


def test_partial_flow_failure_does_not_break_rows() -> None:
    """单只资金流失败只影响该 code 的 main_flow，报价行照常返回。"""
    adapter = FakeAdapter(
        quotes={
            "600519": _quote("600519", "茅", "10", "1"),
            "000001": _quote("000001", "平", "10", "-1"),
        },
        flows={"600519": _flow("1000000")},
        flow_fail_codes={"000001"},
    )
    rows = WatchlistQuoteService(adapter).fetch(["600519", "000001"])
    assert len(rows) == 2
    assert rows[0]["main_flow"] is not None
    assert rows[1]["main_flow"] is None
    assert rows[1]["price"] == Decimal("10")


def test_none_adapter_or_empty_codes_returns_empty() -> None:
    svc = WatchlistQuoteService(None)
    assert svc.fetch(["600519"]) == []
    assert WatchlistQuoteService(FakeAdapter()).fetch([]) == []


def test_flow_worker_cap_is_four() -> None:
    """并发上限常量与设计一致（防打爆上游）。"""
    from mommy_chaogu.services.watchlist_quote_service import FLOW_MAX_WORKERS

    assert FLOW_MAX_WORKERS == 4

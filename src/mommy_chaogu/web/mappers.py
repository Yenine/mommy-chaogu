"""dataclass ↔ Pydantic 转换层。

原则：
- Decimal 全部保留为字符串（前端 Number 接收）
- datetime 全部 ISO 8601（FastAPI 自动处理）
- 不在 mapper 里做数据格式化（格式化在前端）
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import TypedDict, cast

from mommy_chaogu.flows.cumulative import latest_money_flow
from mommy_chaogu.market_data import Bar, MoneyFlow, OrderBook
from mommy_chaogu.market_data.time_utils import market_trade_date
from mommy_chaogu.monitor import Snapshot, SnapshotRow
from mommy_chaogu.portfolio import PortfolioStore
from mommy_chaogu.portfolio.models import Position, PositionAdjustment
from mommy_chaogu.signals.types import Signal
from mommy_chaogu.watchlist.models import Group, StockEntry
from mommy_chaogu.web.schemas import (
    AdjustmentOut,
    BarOut,
    FlowCumulativeOut,
    FlowItemOut,
    HistoryFlowItemOut,
    HistoryFlowOut,
    OrderBookLevelOut,
    OrderBookOut,
    PositionDetailOut,
    PositionOut,
    QuoteOut,
    SignalOut,
    SnapshotOut,
    TodayFlowOut,
    WatchlistGroupOut,
    WatchlistStockOut,
)

_log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _quote_to_out(row: SnapshotRow) -> QuoteOut:
    """SnapshotRow → QuoteOut。"""
    q = row.quote
    flow = row.latest_flow
    main_net = flow.main_net.amount if flow else None
    # 数据年龄（秒）—— 处理 naive datetime（第三方接口经常不返回 tz）
    ts = q.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    age = max(0, int((_utcnow() - ts).total_seconds()))
    return QuoteOut(
        code=q.code,
        name=q.name,
        market=q.market.value,
        price=q.price,
        change=q.change,
        change_pct=q.change_pct,
        volume=int(q.volume),
        turnover=q.turnover.amount,
        open=q.open,
        high=q.high,
        low=q.low,
        prev_close=q.prev_close,
        pe=q.pe_dynamic,
        pb=None,  # 项目当前 Quote 不提供静态 PB
        turnover_rate=q.turnover_rate,
        volume_ratio=q.volume_ratio,
        main_net_inflow=main_net,
        timestamp=ts,
        fetched_at=q.timestamp,  # 装饰器链里 Quote 暂时没区分这两个，先放同一个
        data_age_seconds=age,
    )


def snapshot_to_out(snapshot: Snapshot) -> SnapshotOut:
    """Snapshot → SnapshotOut。"""
    quotes = [_quote_to_out(r) for r in snapshot.rows]
    return SnapshotOut(
        timestamp=snapshot.timestamp,
        quotes=quotes,
        total_main_net=snapshot.total_main_net,
        n_codes=snapshot.n_codes,
        n_up=snapshot.n_up,
        n_down=snapshot.n_down,
        n_flat=snapshot.n_flat,
    )


def bar_to_out(bar: Bar) -> BarOut:
    """Bar → BarOut（adapter 层已统一为 market_data.types.Bar）。"""
    trade_date = market_trade_date(bar.timestamp, bar.code)
    return BarOut(
        timestamp=bar.timestamp,
        trade_date=trade_date,
        adjustment=bar.adjustment.value,
        currency=bar.turnover.currency,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=int(bar.volume),
        turnover=bar.turnover.amount,
    )


def orderbook_to_out(code: str, ob: OrderBook) -> OrderBookOut:
    bids = [OrderBookLevelOut(price=lv.price, volume=int(lv.volume)) for lv in ob.bids]
    asks = [OrderBookLevelOut(price=lv.price, volume=int(lv.volume)) for lv in ob.asks]
    return OrderBookOut(
        code=code,
        timestamp=ob.timestamp,
        bids=bids,
        asks=asks,
    )


# ---------- Money Flow mappers ----------


def _flow_item_to_out(f: MoneyFlow) -> FlowItemOut:
    """MoneyFlow → FlowItemOut（Decimal 保留原值，序列化为 str）。"""
    return FlowItemOut(
        timestamp=f.timestamp,
        main_net=f.main_net.amount,
        super_net=f.super_large_net.amount if f.super_large_net else None,
        big_net=f.large_net.amount if f.large_net else None,
        medium_net=f.medium_net.amount if f.medium_net else None,
        small_net=f.small_net.amount if f.small_net else None,
        main_ratio=f.main_net_ratio,
    )


def today_flow_to_out(flows: Sequence[MoneyFlow]) -> TodayFlowOut:
    """当日资金流 → TodayFlowOut。

    当日累计 = 序列末条（每日累计取末条契约，flows/cumulative）；
    末条缺的分项按 0 展示（与旧 dict 路径的 ``or "0"`` 同口径）。
    """
    items = [_flow_item_to_out(f) for f in flows]
    last = latest_money_flow(flows)
    row = _flow_item_to_out(last) if last is not None else None
    zero = Decimal("0")
    return TodayFlowOut(
        items=items,
        cumulative=FlowCumulativeOut(
            main_net=row.main_net if row is not None else zero,
            super_net=(row.super_net if row is not None else None) or zero,
            big_net=(row.big_net if row is not None else None) or zero,
            medium_net=(row.medium_net if row is not None else None) or zero,
            small_net=(row.small_net if row is not None else None) or zero,
        ),
    )


def history_flow_to_out(flows: Sequence[MoneyFlow], days: int) -> HistoryFlowOut:
    """历史资金流 → HistoryFlowOut（整段累计 = 逐日求和，缺值跳过）。"""
    items = [
        HistoryFlowItemOut(
            **_flow_item_to_out(f).model_dump(),
            date=f.timestamp.strftime("%Y-%m-%d"),
        )
        for f in flows
    ]
    zero = Decimal("0")
    main_total = zero
    totals: dict[str, Decimal] = {
        "super_net": zero,
        "big_net": zero,
        "medium_net": zero,
        "small_net": zero,
    }
    for item in items:
        main_total += item.main_net
        for key in totals:
            amount = getattr(item, key)
            if amount is not None:
                totals[key] += amount
    return HistoryFlowOut(
        items=items,
        cumulative=FlowCumulativeOut(main_net=main_total, **totals),
        days=days,
    )


def stock_entry_to_out(entry: StockEntry, group_name: str) -> WatchlistStockOut:
    """StockEntry → WatchlistStockOut。"""
    name = entry.name or entry.code
    if not entry.name and entry.code:
        # 尝试从缓存里取名字（fallback 用）
        try:
            from mommy_chaogu.cache.store import CacheStore

            from .deps import get_db_path

            with CacheStore(get_db_path()).session() as s:
                from sqlalchemy.sql import text

                rows = s.execute(
                    text("SELECT name FROM quote_cache WHERE code = :c LIMIT 1"),
                    {"c": entry.code},
                ).fetchall()
                if rows and rows[0][0]:
                    name = rows[0][0]
        except Exception as e:
            _log.debug("从 quote_cache 回填名称失败（code=%s）: %s", entry.code, e)
    # 处理 naive datetime
    added_at = entry.created_at
    if added_at.tzinfo is None:
        added_at = added_at.replace(tzinfo=UTC)
    return WatchlistStockOut(
        code=entry.code,
        name=name,
        group=group_name,
        note=entry.note or "",
        added_at=added_at,
    )


def group_to_out(group: Group, n_stocks: int) -> WatchlistGroupOut:
    return WatchlistGroupOut(
        name=group.name,
        description=group.description or "",
        n_stocks=n_stocks,
    )


def signal_to_out(signal: Signal) -> SignalOut:
    return SignalOut(
        timestamp=signal.timestamp,
        code=signal.code,
        name=signal.name,
        rule_id=signal.rule_id,
        severity=signal.severity.value,
        title=signal.title,
        detail=signal.detail,
        trigger_value=signal.trigger_value,
        threshold_value=signal.threshold_value,
    )


# ---------- Portfolio mappers ----------


class PortfolioSummaryItem(TypedDict):
    """store.summary() positions 元素的形状（见 portfolio/store.py summary docstring）。"""

    position: Position
    avg_cost: Decimal
    shares: int
    current_price: Decimal | None
    market_value: Decimal | None
    total_cost: Decimal
    unrealized_pnl: Decimal | None
    unrealized_pnl_pct: Decimal | None


class PortfolioSummaryData(TypedDict):
    """store.summary() 的返回形状（store 侧只标注了 dict[str, object]）。"""

    positions: list[PortfolioSummaryItem]
    total_cost: Decimal
    total_market_value: Decimal
    total_unrealized_pnl: Decimal
    total_unrealized_pnl_pct: Decimal
    n_positions: int


def portfolio_summary(
    store: PortfolioStore,
    current_prices: dict[str, Decimal],
) -> PortfolioSummaryData:
    """带类型地取 store.summary。

    store 层返回 dict[str, object]（web 层不可改），在 web 边界按
    store.summary 的既定契约收窄一次，路由代码即可用真实字段类型。
    """
    return cast("PortfolioSummaryData", store.summary(current_prices))


def _aware(dt: datetime) -> datetime:
    """naive datetime → UTC aware。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def position_to_out(pos: Position) -> PositionOut:
    return PositionOut(
        id=pos.id,
        code=pos.code,
        name=pos.name,
        buy_price=Decimal(pos.buy_price),
        shares=pos.shares,
        buy_date=pos.buy_date,  # date, not datetime
        note=pos.note or "",
        created_at=_aware(pos.created_at),
        updated_at=_aware(pos.updated_at),
    )


def position_detail_to_out(
    pos: Position,
    avg_cost: Decimal,
    shares: int,
    current_price: Decimal | None,
    market_value: Decimal | None,
    total_cost: Decimal,
    unrealized_pnl: Decimal | None,
    unrealized_pnl_pct: Decimal | None,
) -> PositionDetailOut:
    return PositionDetailOut(
        id=pos.id,
        code=pos.code,
        name=pos.name,
        avg_cost=avg_cost,
        shares=shares,
        current_price=current_price,
        market_value=market_value,
        total_cost=total_cost,
        unrealized_pnl=unrealized_pnl,
        unrealized_pnl_pct=unrealized_pnl_pct,
        buy_date=pos.buy_date,  # date, not datetime
        note=pos.note or "",
        created_at=_aware(pos.created_at),
        updated_at=_aware(pos.updated_at),
    )


def adjustment_to_out(adj: PositionAdjustment) -> AdjustmentOut:
    return AdjustmentOut(
        id=adj.id,
        position_id=adj.position_id,
        action=adj.action,
        price=Decimal(adj.price),
        shares=adj.shares,
        timestamp=_aware(adj.timestamp),
        note=adj.note or "",
    )

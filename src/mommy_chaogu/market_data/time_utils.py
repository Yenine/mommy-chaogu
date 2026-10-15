"""Small timestamp helpers shared by market-data consumers.

This module is the single source of truth for A-share timezone semantics:
modules that need ``Asia/Shanghai`` import ``TZ_BEIJING`` / ``beijing_trade_date``
from here instead of keeping private ``ZoneInfo`` copies or ``_SHANGHAI``-style
aliases.  It intentionally does not model exchange holidays or a market
calendar: ``is_a_share_trading_day`` answers only from a supplied set of
observed index/board bar dates and reports ``None`` when the data cannot
decide.
"""

from __future__ import annotations

from collections.abc import Set
from datetime import date, datetime
from zoneinfo import ZoneInfo

#: A 股（及板块代码）交易日历的单一真相源时区；美股代码不在本常量的语义内。
TZ_BEIJING = ZoneInfo("Asia/Shanghai")
_TZ_NEW_YORK = ZoneInfo("America/New_York")


def beijing_trade_date(timestamp: datetime) -> str:
    """K 线/资金流时间戳 → 北京时区交易日字符串（``YYYY-MM-DD``）。

    naive 时间戳防御性地按北京墙时间解释（缓存适配层的历史语义），
    aware 时间戳统一换算到北京时区。
    """
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=TZ_BEIJING)
    return timestamp.astimezone(TZ_BEIJING).strftime("%Y-%m-%d")


def market_trade_date(timestamp: datetime, code: str) -> str:
    """Return a market-local date for A-share/board and US code forms.

    Naive timestamps preserve their historical wall-clock date.  Aware
    timestamps use Beijing for A-share numeric/prefixed/board codes and New
    York for US symbols and ``^`` indices.
    """
    if timestamp.tzinfo is None:
        return timestamp.date().isoformat()
    normalized = code.lower()
    is_a_share_code = len(normalized) == 6 and normalized.isdigit()
    is_prefixed_a_share = (
        len(normalized) == 8 and normalized[:2] in {"sh", "sz", "bj"} and normalized[2:].isdigit()
    )
    is_sector_board = normalized.startswith("bk") and normalized[2:].isdigit()
    timezone = (
        TZ_BEIJING if is_a_share_code or is_prefixed_a_share or is_sector_board else _TZ_NEW_YORK
    )
    return timestamp.astimezone(timezone).date().isoformat()


def is_a_share_trading_day(day: date, known_trade_dates: Set[date]) -> bool | None:
    """判断 *day* 是否 A 股交易日；数据无法判定时返回 ``None``（未知，不猜测）。

    数据源约定（P1）：``known_trade_dates`` 是**指数/板块**日 K 的日期集合
    ——指数与板块每个交易日必有 K 线，集合在其跨度内是完整的交易日记录。
    不得传入个股 K 线日期集合：个股停牌会在跨度内制造假「非交易日」。
    也不得传入 bar_cache 行键的原始集合：历史脏键（见 cache/store.py 读侧
    容错）需先按 bar_json 内 timestamp 反推真实交易日后再归集。

    判定规则：

    - ``day`` 在集合中 → ``True``；
    - 集合非空且 ``day`` 落在 ``[min, max]`` 跨度内但缺席 → ``False``
      （跨度内缺席即非交易日：周末/节假日）；
    - ``day`` 在跨度之外，或集合为空 → ``None``（数据未覆盖，不得猜测）。

    本阶段仅提供谓词本身；是否接入调度/去重/监控行为另行立项。
    """
    if not known_trade_dates:
        return None
    if day in known_trade_dates:
        return True
    if min(known_trade_dates) <= day <= max(known_trade_dates):
        return False
    return None

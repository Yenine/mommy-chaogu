"""Small timestamp helpers shared by market-data consumers.

This module only converts a timestamp to the display/trading date for the
supported code forms.  It intentionally does not model exchange holidays or a
market calendar.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

_TZ_BEIJING = ZoneInfo("Asia/Shanghai")
_TZ_NEW_YORK = ZoneInfo("America/New_York")


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
        _TZ_BEIJING if is_a_share_code or is_prefixed_a_share or is_sector_board else _TZ_NEW_YORK
    )
    return timestamp.astimezone(timezone).date().isoformat()

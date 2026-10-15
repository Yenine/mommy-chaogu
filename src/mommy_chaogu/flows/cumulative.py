"""资金流「每日累计取末条」的单一实现（跨域数值口径契约）。

efinance 的当日/历史资金流每条都是到该时刻的**累计值**：同一交易日的
序列按时间升序，末条才是当日（到取数时刻的）累计，首条只是盘中最早
快照。取「当日代表值」一律经本模块，不得在决策点各自 ``flows[-1]`` /
``flows[0]``——历史上 backtest 取首条而实盘取末条，造成回测与实盘口径
系统性不一致。

已迁移的决策点（新增当日取值点时必须走本模块，并保持本清单同步）：
- flows 域：flows/service.py（当日 + 按日历史聚合）、flows/monitor.py、
  flows/report.py（当日 + 历史 30d）
- agent 层：agent/tools/flows.py（单只 + 批量）、agent/tools/analysis.py
  （flow_in 筛选）、agent/monitor.py（_get_latest_flow）
- 展示层：services/watchlist_quote_service.py、services/theme_service.py、
  web/mappers.py（money_flow 端点当日累计）、monitor/poller.py（快照行回填）
- 回测：backtest/engine.py（按日回放）

注意两个「ratio」口径不同，数值不可互换：
- flows 域与回测的 ratio = 主力净流入 ÷ 流通市值（小数，5bp = 0.0005）；
- efinance ``main_net_ratio`` = 主力净流入占**成交额**的 %（5.2 = 5.2%）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from mommy_chaogu.market_data.types import MoneyFlow


def latest_flow_row(flows: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """每日累计序列的代表值 = 末条（dict 行核心，缓存 JSON 行形态）。

    空序列返回 None。上游按时间升序写入/返回（缓存命中整段回放、拉新
    整段覆盖，均保持升序），因此末条即最新累计。
    """
    return flows[-1] if flows else None


def latest_money_flow(flows: Sequence[MoneyFlow]) -> MoneyFlow | None:
    """每日累计序列的代表值 = 末条（MoneyFlow 适配）。

    空序列返回 None。与 :func:`latest_flow_row` 同一口径，供 adapter /
    service 直接返回 ``MoneyFlow`` 的路径使用。
    """
    return flows[-1] if flows else None

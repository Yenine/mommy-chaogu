"""资金流工具：当日主力净流入、历史资金流。"""

from __future__ import annotations

from typing import Any

from mommy_chaogu.agent.tools.base import ToolContext, ToolDef, ToolHandler, _clamp_int, _json
from mommy_chaogu.flows.cumulative import latest_money_flow

DEFS: list[ToolDef] = [
    ToolDef(
        name="get_money_flow_today",
        description=(
            "获取股票当日资金流明细（主力/超大单/大单/中单/小单净流入）。"
            "单只用 code；多只（如批量查自选股）用 codes 列表，最多处理前 10 只。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "pattern": "^([A-Z]{1,6}|\\d{6})$",
                    "description": "股票代码（A 股 6 位数字或美股字母，单只，与 codes 二选一。注意：资金流为 A 股特有数据，美股无此概念）",
                },
                "codes": {
                    "type": "array",
                    "items": {"type": "string", "pattern": "^([A-Z]{1,6}|\\d{6})$"},
                    "description": "股票代码列表（多只批量查询，最多前 10 只，与 code 二选一。注意：资金流为 A 股特有数据，美股无此概念）",
                },
            },
        },
    ),
    ToolDef(
        name="get_money_flow_history",
        description="获取单只股票历史 N 天资金流（每日主力净流入等）。",
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "pattern": "^([A-Z]{1,6}|\\d{6})$",
                    "description": "股票代码（A 股 6 位数字或美股字母）",
                },
                "days": {
                    "type": "integer",
                    "description": "历史天数，默认 7（最大 365）",
                    "default": 7,
                    "minimum": 1,
                    "maximum": 365,
                },
            },
            "required": ["code"],
        },
    ),
]


def _today_flow_meta(ctx: ToolContext) -> dict[str, str | None]:
    """本次当日资金流取数的 (数据交易日, 来源) 标注。

    CachedMarketDataAdapter 在 get_today_money_flow 的每条返回路径都维护
    ``last_source_trade_date``（缓存命中路径即缓存行的 trade_date 镜像）与
    ``last_source``；裸 adapter 无这两个属性 → 标注 None（数值本身不变，
    只是无法标注），与 bars.py 的 data_source 同款降级。
    """
    trade_date = getattr(ctx.adapter, "last_source_trade_date", "")
    source = getattr(ctx.adapter, "last_source", "")
    return {
        "trade_date": trade_date if isinstance(trade_date, str) and trade_date else None,
        "data_source": source if isinstance(source, str) and source else None,
    }


def _flow_to_dict(
    latest: Any,
    *,
    trade_date: str | None = None,
    data_source: str | None = None,
) -> dict[str, Any]:
    return {
        "code": latest.code,
        "name": latest.name,
        "timestamp": latest.timestamp.isoformat(),
        # 数据日期契约（P3）：当日输出自带数据交易日与来源，节假日命中的
        # 上一交易日缓存可被宿主识别，不再被当当日
        "trade_date": trade_date,
        "data_source": data_source,
        "main_net": float(latest.main_net.amount),
        "super_large_net": float(latest.super_large_net.amount),
        "large_net": float(latest.large_net.amount),
        "medium_net": float(latest.medium_net.amount),
        "small_net": float(latest.small_net.amount),
        "main_net_ratio": float(latest.main_net_ratio) if latest.main_net_ratio else None,
    }


def _handle_get_money_flow_today(ctx: ToolContext, args: dict[str, Any]) -> str:
    codes_arg = args.get("codes")
    if codes_arg is not None:
        if not isinstance(codes_arg, list) or not codes_arg:
            return _json({"error": "codes 必须是非空股票代码列表"})
        return _handle_multi_money_flow_today(ctx, [str(c) for c in codes_arg[:10]])

    code = args.get("code")
    if not code:
        return _json({"error": "需要 code（单只）或 codes（多只）参数"})
    flows = ctx.adapter.get_today_money_flow(code)
    # 每日累计取末条契约（flows/cumulative）：空序列与未找到统一为 error
    latest = latest_money_flow(flows)
    if latest is None:
        return _json({"error": f"未找到 {code} 的当日资金流"})
    return _json(_flow_to_dict(latest, **_today_flow_meta(ctx)))


def _handle_multi_money_flow_today(ctx: ToolContext, codes: list[str]) -> str:
    """批量查询当日资金流（最多 10 只，调用方负责截断）。

    单只失败不影响其他；全部失败时返回顶层 error（让 workflow 识别为失败步骤）。
    """
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for code in codes:
        try:
            flows = ctx.adapter.get_today_money_flow(code)
        except Exception as e:
            errors[code] = str(e)
            continue
        latest = latest_money_flow(flows)  # 每日累计取末条契约（flows/cumulative）
        if latest is None:
            errors[code] = "未找到当日资金流"
            continue
        results[code] = _flow_to_dict(latest, **_today_flow_meta(ctx))

    if not results:
        return _json({"error": "所有股票的当日资金流均不可用", "errors": errors})
    payload: dict[str, Any] = {"results": results, "count": len(results)}
    if errors:
        payload["errors"] = errors
    return _json(payload)


def _handle_get_money_flow_history(ctx: ToolContext, args: dict[str, Any]) -> str:
    code = args["code"]
    days = _clamp_int(args.get("days", 7), 7, 1, 365)
    flows = ctx.adapter.get_history_money_flow(code, days=days)
    return _json(
        [
            {
                "code": f.code,
                "name": f.name,
                "timestamp": f.timestamp.isoformat(),
                "main_net": float(f.main_net.amount),
                "super_large_net": float(f.super_large_net.amount),
                "large_net": float(f.large_net.amount),
                "medium_net": float(f.medium_net.amount),
                "small_net": float(f.small_net.amount),
                "main_net_ratio": float(f.main_net_ratio) if f.main_net_ratio else None,
            }
            for f in flows
        ]
    )


HANDLERS: dict[str, ToolHandler] = {
    "get_money_flow_today": _handle_get_money_flow_today,
    "get_money_flow_history": _handle_get_money_flow_history,
}

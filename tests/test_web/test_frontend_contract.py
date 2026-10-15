"""前后端契约对照（P6）：把两类漂移变成 CI 可拦截的失败。

1. REST：关键端点 OpenAPI schema 的 properties ↔ 前端 TS interface 字段
   集合做**双向包含**对比（基于 properties 而非 required——后端新增字段
   而前端未跟进必须红），允许带理由的显式豁免。
2. WS：ws.py 发出的事件类型常量集合 ↔ 前端 agentSocket.ts 的 case 分支
   ——后端新增事件类型不改前端即红。

不落快照文件：断言直接从 ``create_app().openapi()`` 与前端源文件生成，
契约漂移在当次运行就暴露，无需维护快照。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest

from mommy_chaogu.web.routes.ws import AGENT_WS_EVENT_TYPES, MARKET_WS_EVENT_TYPES

REPO_ROOT = Path(__file__).resolve().parents[2]
# 前端类型声明来源：types.ts 是主契约文件；AgentInfo / SessionSummary 等
# agent 域类型就近声明在 api/agent.ts。
FRONTEND_TYPE_SOURCES = ("api/types.ts", "api/agent.ts")
AGENT_SOCKET_TS = REPO_ROOT / "web" / "src" / "lib" / "agentSocket.ts"
WS_ROUTE_PY = REPO_ROOT / "src" / "mommy_chaogu" / "web" / "routes" / "ws.py"

# 关键端点 → 200 响应的根 schema 组件名（数组端点取 items 的组件名）。
# 断言它们必须有 response_model：无 schema 的端点是 openapi 盲区，
# 字段漂移对前端不可见。
ENDPOINT_ROOT_SCHEMAS: dict[tuple[str, str], str] = {
    ("GET", "/api/quotes"): "SnapshotOut",
    ("GET", "/api/quotes/{code}"): "QuoteOut",
    ("GET", "/api/quotes/{code}/money_flow/today"): "TodayFlowOut",
    ("GET", "/api/quotes/{code}/money_flow/history"): "HistoryFlowOut",
    ("GET", "/api/market/indexes"): "IndexOut",
    ("GET", "/api/portfolio"): "PortfolioSummaryOut",
    ("GET", "/api/signals/recent"): "SignalOut",
    ("GET", "/api/signals/history"): "SignalOut",
    ("GET", "/api/agent/info"): "AgentInfoOut",
    ("GET", "/api/agent/sessions"): "AgentSessionsOut",
}

# 后端 schema 组件名 → 前端 interface 名（嵌套 schema 一并对照；
# 同一前端 interface 可对照多个后端 schema）。
SCHEMA_INTERFACE_PAIRS: dict[str, str] = {
    "SnapshotOut": "Snapshot",
    "QuoteOut": "Quote",
    "FlowItemOut": "MoneyFlowItem",
    "HistoryFlowItemOut": "MoneyFlowItem",
    "FlowCumulativeOut": "MoneyFlowCumulative",
    "TodayFlowOut": "MoneyFlowResponse",
    "HistoryFlowOut": "MoneyFlowResponse",
    "IndexOut": "IndexQuote",
    "PortfolioSummaryOut": "PortfolioSummary",
    "PositionDetailOut": "PositionDetail",
    "SignalOut": "Signal",
    "AgentInfoOut": "AgentInfo",
    "AgentSessionSummaryOut": "SessionSummary",
}

# 双向对照的显式豁免：(schema, interface) → {字段: 理由}。
# 每条豁免必须写明理由；无理由的漂移一律红。当前仅剩「一个前端
# interface 服务两个后端 schema」造成的可选字段差。
EXEMPT_FIELDS: dict[tuple[str, str], dict[str, str]] = {
    ("FlowItemOut", "MoneyFlowItem"): {
        "date": "MoneyFlowItem 同时描述 today/history 条目；date 仅历史条目（HistoryFlowItemOut）返回",
    },
    ("TodayFlowOut", "MoneyFlowResponse"): {
        "days": "MoneyFlowResponse 同时描述 today/history 响应；days 仅 history（HistoryFlowOut）返回",
    },
}

# agentSocket.ts 的显式豁免：事件类型 → 不处理该事件的理由。默认为空
# ——后端新增事件类型必须同步前端 dispatch 分支，豁免是例外不是常态。
AGENT_SOCKET_EXEMPT: dict[str, str] = {}


@pytest.fixture(scope="module")
def openapi_schema() -> dict[str, Any]:
    from mommy_chaogu.web.app import create_app

    return dict(create_app().openapi())


# ---------- 前端 TS 解析 ----------


def _frontend_interface_fields(interface: str) -> set[str]:
    """提取 TS interface 顶层字段名（含 ``name?:`` 可选字段）。

    只在 interface 自身花括号深度上取字段，跳过嵌套对象/数组类型与
    注释行；所有类型来源文件都没声明该 interface 时直接判失败。
    """
    for rel in FRONTEND_TYPE_SOURCES:
        source = (REPO_ROOT / "web" / "src" / rel).read_text(encoding="utf-8")
        m = re.search(rf"export interface {interface}\b[^{{]*\{{", source)
        if m is None:
            continue
        fields: set[str] = set()
        depth = 1
        for line in source[m.end() :].splitlines():
            stripped = line.strip()
            if (
                depth == 1
                and not stripped.startswith(("//", "*", "/*"))
                and (fm := re.match(r"(?:readonly\s+)?([A-Za-z_$][\w$]*)\??:", stripped))
            ):
                fields.add(fm.group(1))
            depth += line.count("{") - line.count("}")
            if depth == 0:
                break
        return fields
    raise AssertionError(f"前端未声明 interface {interface}（查找范围: {FRONTEND_TYPE_SOURCES}）")


# ---------- OpenAPI 解析 ----------


def _response_schema(spec: dict[str, Any], method: str, path: str) -> dict[str, Any]:
    try:
        operation = spec["paths"][path][method.lower()]
        return operation["responses"]["200"]["content"]["application/json"]["schema"]
    except (KeyError, TypeError) as exc:
        raise AssertionError(
            f"{method.upper()} {path} 缺少 JSON 响应 schema（openapi 盲区）"
        ) from exc


def _root_component_name(schema: dict[str, Any]) -> str | None:
    """响应根 schema 的组件名（$ref 或数组 items 的 $ref；无 ref 即盲区）。"""
    if "$ref" in schema:
        return str(schema["$ref"]).rsplit("/", 1)[-1]
    if schema.get("type") == "array":
        return _root_component_name(schema["items"])
    return None


def _referenced_components(
    schema: Any,
    components: dict[str, Any],
    seen: set[str] | None = None,
) -> set[str]:
    """递归收集 schema 引用到的全部组件名（含根 $ref）。"""
    seen = set() if seen is None else seen
    if isinstance(schema, dict):
        if "$ref" in schema:
            name = str(schema["$ref"]).rsplit("/", 1)[-1]
            if name not in seen:
                seen.add(name)
                _referenced_components(components.get(name, {}), components, seen)
        else:
            for value in schema.values():
                _referenced_components(value, components, seen)
    elif isinstance(schema, list):
        for item in schema:
            _referenced_components(item, components, seen)
    return seen


# ---------- REST 契约 ----------


def test_key_endpoints_have_response_model(openapi_schema: dict[str, Any]) -> None:
    """关键端点必须有 response_model——无 schema 的响应是 openapi 盲区。"""
    for (method, path), expected in ENDPOINT_ROOT_SCHEMAS.items():
        root = _root_component_name(_response_schema(openapi_schema, method, path))
        assert root == expected, (
            f"{method.upper()} {path} 响应根 schema 应为 {expected}，实际 {root}"
        )


def test_compared_schemas_reachable_from_key_endpoints(openapi_schema: dict[str, Any]) -> None:
    """对照清单里的 schema 必须仍被关键端点引用（防止比较已脱钩的孤儿）。"""
    components = openapi_schema["components"]["schemas"]
    reachable: set[str] = set()
    for method, path in ENDPOINT_ROOT_SCHEMAS:
        reachable |= _referenced_components(
            _response_schema(openapi_schema, method, path), components
        )
    orphans = set(SCHEMA_INTERFACE_PAIRS) - reachable
    assert not orphans, f"对照清单中的 schema 已不被关键端点引用: {sorted(orphans)}"


def test_backend_properties_match_frontend_interfaces(openapi_schema: dict[str, Any]) -> None:
    """schema properties ↔ 前端 interface 字段双向包含。

    - 后端多出的字段 = 「后端新增字段前端未跟进」（基于 properties，
      与 required 无关——可选字段同样是前端可消费的契约）；
    - 前端多出的字段 = 「前端声明了后端已不返回的字段」（误导性声明）。
    """
    components = openapi_schema["components"]["schemas"]
    for schema_name, interface in SCHEMA_INTERFACE_PAIRS.items():
        assert schema_name in components, f"openapi 缺少组件 {schema_name}"
        backend_fields = set(components[schema_name].get("properties", {}))
        frontend_fields = _frontend_interface_fields(interface)
        exempt = set(EXEMPT_FIELDS.get((schema_name, interface), {}))

        backend_only = backend_fields - frontend_fields - exempt
        assert not backend_only, (
            f"后端 {schema_name} 的字段 {sorted(backend_only)} "
            f"前端 interface {interface} 未声明——需同步前端类型或列入豁免清单"
        )
        frontend_only = frontend_fields - backend_fields - exempt
        assert not frontend_only, (
            f"前端 {interface} 声明的字段 {sorted(frontend_only)} "
            f"后端 {schema_name} 不再返回——需删除前端声明或列入豁免清单"
        )


# ---------- WS 事件契约 ----------


def _emitted_ws_event_types(source: str) -> set[str]:
    """ws.py 源码里所有 ``{"type": "<literal>"}`` dict 字面量的事件类型。

    用 AST 而非正则：只统计真实代码里的 dict 构造——docstring 里的协议
    示例（如客户端→服务端的 confirm/cancel）与 ``peek.get("type")`` 比较
    都不会误入，得到的恰好是服务端→客户端的全部发出类型。
    """
    emitted: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=False):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "type"
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                ):
                    emitted.add(value.value)
    return emitted


def test_ws_emitted_event_types_all_registered() -> None:
    """ws.py 发出的每个 "type" 字面量都必须登记进常量集合（真相源纪律）。

    双向：发出未登记 = 绕过契约；登记未发出 = 手误或过时常量。
    """
    emitted = _emitted_ws_event_types(WS_ROUTE_PY.read_text(encoding="utf-8"))
    registered = AGENT_WS_EVENT_TYPES | MARKET_WS_EVENT_TYPES
    unregistered = emitted - registered
    assert not unregistered, f"ws.py 发出的事件类型未登记进常量集合: {sorted(unregistered)}"
    never_emitted = registered - emitted
    assert not never_emitted, f"常量集合登记的事件类型 ws.py 并不发出: {sorted(never_emitted)}"


def test_agent_socket_handles_every_agent_event_type() -> None:
    """前端 agentSocket.ts 必须对每个 /ws/agent 事件类型有处理分支。

    后端新增事件类型 → 必须先登记 AGENT_WS_EVENT_TYPES（上一测试），
    再在前端 dispatch 加 case，否则此处红。
    """
    source = AGENT_SOCKET_TS.read_text(encoding="utf-8")
    unhandled = {
        event
        for event in AGENT_WS_EVENT_TYPES
        if f"case '{event}':" not in source and event not in AGENT_SOCKET_EXEMPT
    }
    assert not unhandled, (
        f"/ws/agent 事件 {sorted(unhandled)} 前端 agentSocket.ts 未处理"
        f"——需同步 dispatch 分支或注明豁免理由"
    )

"""/ws 路由：WebSocket 实时推送。

端点：
- WS /ws/quotes   — 推送最新报价快照（每 5s）
- WS /ws/signals  — 推送触发的信号（有就推）
"""

from __future__ import annotations

import itertools
import logging
import threading
from typing import Annotated, Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from mommy_chaogu.agent.service import ChatCallbacks, is_denial_result
from mommy_chaogu.preferences import default_preferences
from mommy_chaogu.web.agent_context import AgentPageContext, page_context_addendum
from mommy_chaogu.web.background import BackgroundService, get_service
from mommy_chaogu.web.mappers import signal_to_out, snapshot_to_out
from mommy_chaogu.web.trading_style import preference_context

_log = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


# ---------- 辅助函数 ----------


async def push_snapshot(ws: WebSocket, snapshot: Any) -> None:
    """推送报价快照。"""
    payload = snapshot_to_out(snapshot).model_dump(mode="json")
    await ws.send_json({"type": "quote_update", "snapshot": payload})


async def push_signals(ws: WebSocket, signals: list[Any]) -> None:
    """推送信号列表。"""
    payload = [signal_to_out(s).model_dump(mode="json") for s in signals]
    await ws.send_json({"type": "signal_triggered", "signals": payload})


# ---------- 端点 ----------


async def _authorize(websocket: WebSocket) -> bool:
    security = websocket.app.state.web_security
    if security.validate_ws_ticket(websocket.query_params.get("ticket")):
        return True
    await websocket.close(code=1008, reason="Missing or invalid WebSocket ticket")
    return False


@router.websocket("/ws/quotes")
async def ws_quotes(
    websocket: WebSocket,
    service: Annotated[BackgroundService, Depends(get_service)],
) -> None:
    """报价快照推送。"""
    if not await _authorize(websocket):
        return
    await websocket.accept()
    await service.add_quote_subscriber(websocket)
    try:
        # 保持连接，接收客户端心跳（无业务消息，只是 keep-alive）
        while True:
            msg = await websocket.receive_text()
            # 简单回 pong（前端用来检测断线）
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        service.remove_quote_subscriber(websocket)


@router.websocket("/ws/signals")
async def ws_signals(
    websocket: WebSocket,
    service: Annotated[BackgroundService, Depends(get_service)],
) -> None:
    """信号推送。"""
    if not await _authorize(websocket):
        return
    await websocket.accept()
    await service.add_signal_subscriber(websocket)
    try:
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        service.remove_signal_subscriber(websocket)


# ---------- Agent 流式对话 WebSocket ----------

# 写操作确认等待用户决定的最长时间（秒）；超时按拒绝处理，worker 线程不悬空
_CONFIRM_TIMEOUT_S = 600.0

_WRITE_LABELS = {
    "manage_watchlist": "修改自选股",
    "manage_alert": "修改提醒",
    "update_prediction_stage": "推进预测阶段",
    "strategy_save": "保存策略卡",
    "strategy_archive": "归档策略卡",
    "strategy_activate_monitor": "启用策略监控",
    "backfill_history": "回填历史数据",
}


def describe_write(name: str, args: dict[str, Any]) -> str:
    """写操作确认条的人话描述：「保存策略卡：均线压制观察 v2」。"""
    label = _WRITE_LABELS.get(name, name)
    key = next(
        (str(args[k]) for k in ("name", "title", "code", "symbol", "action") if k in args), ""
    )
    return f"{label}：{key}" if key else label


class _Turn:
    """一轮对话的控制面：取消信号 + 待决的写操作确认（跨线程）。"""

    def __init__(self) -> None:
        self.cancel = threading.Event()
        self.pending: dict[str, tuple[threading.Event, list[str]]] = {}
        self._lock = threading.Lock()
        self._seq = itertools.count(1)

    def open_confirm(self) -> tuple[str, threading.Event, list[str]]:
        rid = f"c{next(self._seq)}"
        decided: threading.Event = threading.Event()
        box: list[str] = []
        with self._lock:
            self.pending[rid] = (decided, box)
        return rid, decided, box

    def resolve(self, rid: str, decision: str) -> bool:
        with self._lock:
            item = self.pending.pop(rid, None)
        if item is None:
            return False
        item[1].append(decision)
        item[0].set()
        return True

    def abort(self) -> None:
        """中断 / 断线：取消整轮，所有待决确认按拒绝落定。"""
        self.cancel.set()
        with self._lock:
            items = list(self.pending.values())
            self.pending.clear()
        for decided, box in items:
            box.append("deny")
            decided.set()


@router.websocket("/ws/agent")
async def ws_agent(websocket: WebSocket) -> None:
    """AI 对话流式 WebSocket（真流式：逐 LLM delta 转发 + 工具调用事件）。

    客户端 → 服务端：
    - {"message": "...", "session_id": "...", "page_context": {...}}   发起一轮
    - {"type": "confirm", "id": "c1", "decision": "allow|deny|always"} 回应写操作确认
    - {"type": "cancel"}                                               中断当前轮（Esc）

    服务端 → 客户端：
    - {"type": "thinking"}                                     一次（本轮开始）
    - {"type": "thinking_delta", "text": "..."}                推理模型的思考流（可选）
    - {"type": "tool_call_started", "tool", "args"}            每次工具执行前
    - {"type": "tool_call_finished", "tool", "status": "done|fail|denied", "elapsed_ms", "result"}
    - {"type": "confirm_required", "id", "tool", "args", "description"}  写操作执行前等待决定
    - {"type": "retry", "attempt", "max"}                      网络慢、正在重试
    - {"type": "chunk", "text": "..."}                         多次，真实 LLM delta
    - {"type": "usage", "prompt_tokens", "completion_tokens", "total_tokens"}  本轮用量
    - {"type": "interrupted"}                                  本轮被中断（不入记忆）
    - {"type": "done", "tools_used": [...], "rounds": N}
    - {"type": "predictions_created", "count", "predictions"}  done 之后异步到达（可选）

    控制消息（confirm / cancel）由独立的读取任务即时处理，agent 在 worker 线程里
    跑的同时也能收到；「本会话不再询问」按连接记忆，断线即失效。
    兜底：若 agent 层流式不可用（provider 不支持 stream），on_chunk 不会
    被调用，此时把 resp.text 作为单个 chunk 补发，保证前端一定有回答。
    """
    import asyncio
    import json

    if not await _authorize(websocket):
        return
    await websocket.accept()

    from mommy_chaogu.web.deps import (
        get_agent_memory,
        get_agent_service,
        get_portfolio_store,
        get_watchlist_store,
    )

    agent = get_agent_service()
    memory = get_agent_memory()
    always_allow: set[str] = set()
    current: _Turn | None = None
    inbox: asyncio.Queue[str | None] = asyncio.Queue()

    async def _reader() -> None:
        """独立读取：控制消息立即生效，其余消息排队给主循环。"""
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    peek = json.loads(raw)
                except json.JSONDecodeError:
                    peek = None
                if isinstance(peek, dict) and peek.get("type") in ("confirm", "cancel"):
                    turn = current
                    if turn is None:
                        continue
                    if peek["type"] == "cancel":
                        turn.abort()
                    else:
                        decision = peek.get("decision")
                        if decision not in ("allow", "deny", "always"):
                            decision = "deny"
                        turn.resolve(str(peek.get("id", "")), decision)
                    continue
                await inbox.put(raw)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            if current is not None:
                current.abort()
            await inbox.put(None)

    reader_task = asyncio.create_task(_reader())

    try:
        while True:
            raw = await inbox.get()
            if raw is None:
                break

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "无效的 JSON"})
                continue

            if not isinstance(msg, dict):
                await websocket.send_json({"type": "error", "message": "无效的消息格式"})
                continue

            raw_message = msg.get("message", "")
            if not isinstance(raw_message, str):
                await websocket.send_json({"type": "error", "message": "无效的消息格式"})
                continue

            user_message = raw_message.strip()
            if not user_message:
                continue

            session_id = msg.get("session_id", "web-default")
            # 交易风格等偏好由服务端持有（/api/preferences），不再从客户端读取；
            # 每条消息读取一次，偏好修改即时生效；读取失败回落默认值。
            try:
                prefs = get_watchlist_store().get_user_preferences()
            except Exception as exc:
                _log.warning("读取用户偏好失败，Agent 使用默认偏好: %s", exc)
                prefs = default_preferences()
            try:
                raw_page_context = msg.get("page_context")
                page_context = (
                    AgentPageContext.model_validate(raw_page_context)
                    if raw_page_context is not None
                    else None
                )
            except ValidationError:
                await websocket.send_json({"type": "error", "message": "无效的页面上下文"})
                continue
            try:
                session_memory = memory.for_session(session_id)
            except (TypeError, ValueError):
                await websocket.send_json({"type": "error", "message": "无效的会话 ID"})
                continue

            if agent is None:
                await websocket.send_json(
                    {
                        "type": "done",
                        "text": "AI 助手未配置。",
                        "tools_used": [],
                        "rounds": 0,
                    }
                )
                continue

            # thinking 状态
            await websocket.send_json({"type": "thinking"})

            security = websocket.app.state.web_security
            if not await security.try_acquire_agent():
                await websocket.send_json({"type": "error", "message": "AI 助手忙，请稍后重试"})
                continue

            turn = _Turn()
            current = turn

            # 真流式：asyncio.Queue 桥接 worker 线程的所有回调 → 事件循环发送，保证顺序。
            loop = asyncio.get_running_loop()
            event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
            streamed_any = False  # on_chunk 是否真的推过 delta（流式不可用时为 False）
            usage: dict[str, int] = {}

            def _emit(event: dict[str, Any]) -> None:
                """worker 线程内调用，线程安全地把事件推入 queue。"""
                loop.call_soon_threadsafe(event_queue.put_nowait, event)  # noqa: B023

            def on_chunk(delta: str) -> None:
                nonlocal streamed_any
                streamed_any = True
                _emit({"type": "chunk", "text": delta})

            def on_thinking(delta: str) -> None:
                _emit({"type": "thinking_delta", "text": delta})

            def on_tool_call(fn_name: str, fn_args: dict[str, Any]) -> None:
                _emit({"type": "tool_call_started", "tool": fn_name, "args": fn_args})

            def on_tool_result(fn_name: str, success: bool, elapsed_ms: int, digest: str) -> None:
                if success:
                    status = "done"
                elif is_denial_result(digest):
                    # 写操作被用户拒绝 ≠ 执行失败；前端按 denied 渲染「已拒绝」
                    status = "denied"
                else:
                    status = "fail"
                _emit(
                    {
                        "type": "tool_call_finished",
                        "tool": fn_name,
                        "status": status,
                        "elapsed_ms": elapsed_ms,
                        "result": digest,
                    }
                )

            def on_status(status: str, info: dict[str, Any]) -> None:
                if status == "retry":
                    _emit(
                        {
                            "type": "retry",
                            "attempt": int(info.get("attempt", 1)),
                            # 回调的 max 是总尝试次数（重试上限 + 1）
                            "max": max(1, int(info.get("max", 2)) - 1),
                        }
                    )

            def on_confirm(fn_name: str, fn_args: dict[str, Any]) -> bool:
                """写操作确认：worker 线程内阻塞等待前端决定（中断 / 断线 / 超时按拒绝）。"""
                if fn_name in always_allow:
                    return True
                rid, decided, box = turn.open_confirm()  # noqa: B023
                _emit(
                    {
                        "type": "confirm_required",
                        "id": rid,
                        "tool": fn_name,
                        "args": fn_args,
                        "description": describe_write(fn_name, fn_args),
                    }
                )
                if not decided.wait(_CONFIRM_TIMEOUT_S):
                    turn.resolve(rid, "deny")  # noqa: B023
                choice = box[0] if box else "deny"
                if choice == "always":
                    always_allow.add(fn_name)
                return choice in ("allow", "always")

            def on_predictions_created(predictions: list[dict[str, Any]]) -> None:
                """后台提取线程回调：本轮新建的预测 → predictions_created 事件。

                事件在 agent.chat 返回、done 帧发出之后才从后台线程到达，
                不走 event_queue（drain 已结束），直接调度协程发送；
                socket 已关 / loop 已停时静默降级，绝不影响后台线程。
                """

                async def _send() -> None:
                    try:
                        await websocket.send_json(
                            {
                                "type": "predictions_created",
                                "count": len(predictions),
                                "predictions": predictions,
                            }
                        )
                    except Exception as exc:
                        _log.warning("predictions_created 推送失败（连接可能已关闭）: %s", exc)

                def _schedule() -> None:
                    # 持有 task 引用直至完成（RUF006），异常已在 _send 内部捕获
                    task = asyncio.ensure_future(_send())
                    task.add_done_callback(lambda _t: None)

                try:
                    loop.call_soon_threadsafe(_schedule)  # noqa: B023
                except RuntimeError:
                    _log.debug("predictions_created: event loop 已关闭，丢弃事件")

            async def _drain_stream() -> None:
                """持续从 queue 取事件发给前端，直到收到 None sentinel。"""
                while True:
                    event = await event_queue.get()  # noqa: B023
                    if event is None:
                        break
                    await websocket.send_json(event)

            # 启动 drain task，与 agent.chat worker 并发
            drain_task = asyncio.create_task(_drain_stream())
            try:
                addenda = [preference_context(prefs)]
                if page_addendum := page_context_addendum(
                    page_context,
                    get_portfolio_store(),
                    get_watchlist_store(),
                ):
                    addenda.append(page_addendum)
                resp = await asyncio.to_thread(
                    agent.chat,
                    user_message,
                    memory=session_memory,
                    system_addendum="\n\n".join(addenda),
                    callbacks=ChatCallbacks(
                        on_tool_call=on_tool_call,
                        on_tool_result=on_tool_result,
                        on_chunk=on_chunk,
                        on_status=on_status,
                        on_predictions_created=on_predictions_created,
                        on_confirm=on_confirm,
                        on_thinking=on_thinking,
                        cancel_event=turn.cancel,
                        usage_out=usage,
                    ),
                )
            finally:
                current = None
                turn.abort()  # 兜底：任何悬空确认落定为拒绝
                # 通知 drain 结束 + 等 drain 把剩余事件发完
                loop.call_soon_threadsafe(event_queue.put_nowait, None)
                await drain_task
                await security.release_agent()

            if getattr(resp, "interrupted", False) is True:
                await websocket.send_json({"type": "interrupted"})
            # 流式兜底：on_chunk 从未触发（provider 不支持 stream）时，
            # 把非流式兜底文本作为单个 chunk 补发，否则前端会收到空回答。
            elif not streamed_any and resp.text:
                await websocket.send_json({"type": "chunk", "text": resp.text})

            if usage_payload := _usage_payload(usage, getattr(resp, "usage", None)):
                await websocket.send_json({"type": "usage", **usage_payload})

            await websocket.send_json(
                {
                    "type": "done",
                    "tools_used": [tc.name for tc in resp.tool_calls],
                    "rounds": resp.rounds,
                }
            )

    except WebSocketDisconnect:
        pass
    finally:
        if current is not None:
            current.abort()
        reader_task.cancel()


def _usage_payload(*sources: Any) -> dict[str, int]:
    """取第一份有效的 token 用量（usage_out 实时累加 / resp.usage 兜底）。"""
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    for src in sources:
        if isinstance(src, dict) and any(isinstance(src.get(k), int) and src.get(k) for k in keys):
            out = {k: int(src.get(k) or 0) for k in keys}
            if not out["total_tokens"]:
                out["total_tokens"] = out["prompt_tokens"] + out["completion_tokens"]
            return out
    return {}

"""/ws/agent 控制通道：写操作确认、Esc 中断、思考流、重试、token 用量。

网页版（设计稿单页）依赖这些事件实现与终端版一致的交互：
确认条 y/n/a、esc 中断当前轮、思考折叠、底栏 token 常驻。
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from mommy_chaogu.preferences import default_preferences
from mommy_chaogu.web.routes.ws import describe_write


def _install(monkeypatch: Any, fake_chat: Any) -> MagicMock:
    from mommy_chaogu.web import deps

    agent = MagicMock()
    agent.chat.side_effect = fake_chat
    memory = MagicMock()
    store = MagicMock()
    store.get_user_preferences.return_value = default_preferences()
    monkeypatch.setattr(deps, "get_agent_service", lambda: agent)
    monkeypatch.setattr(deps, "get_agent_memory", lambda: memory)
    monkeypatch.setattr(deps, "get_watchlist_store", lambda: store)
    monkeypatch.setattr("mommy_chaogu.web.routes.ws.page_context_addendum", lambda *_args: "")
    return agent


def _resp(text: str = "好的", **extra: Any) -> SimpleNamespace:
    return SimpleNamespace(text=text, tool_calls=[], rounds=1, **extra)


def _until(ws: Any, kind: str, limit: int = 20) -> dict[str, Any]:
    for _ in range(limit):
        msg = ws.receive_json()
        if msg.get("type") == kind:
            return msg
    raise AssertionError(f"没有等到 {kind}")


class TestWriteConfirmation:
    def _confirming_chat(self, seen: list[bool]) -> Any:
        def fake_chat(message: str, *args: Any, **kwargs: Any) -> SimpleNamespace:
            cb = kwargs["callbacks"]
            for _ in range(2):  # 同一工具两次：验证「本会话不再询问」
                seen.append(cb.on_confirm("strategy_save", {"name": "均线压制观察 v2"}))
            cb.on_chunk("完成")
            return _resp()

        return fake_chat

    def test_allow_then_deny(self, client: TestClient, monkeypatch: Any) -> None:
        seen: list[bool] = []
        _install(monkeypatch, self._confirming_chat(seen))
        with client.websocket_connect("/ws/agent") as ws:
            ws.send_json({"message": "保存策略卡"})
            req = _until(ws, "confirm_required")
            assert req["tool"] == "strategy_save"
            assert req["description"] == "保存策略卡：均线压制观察 v2"
            ws.send_json({"type": "confirm", "id": req["id"], "decision": "allow"})
            req2 = _until(ws, "confirm_required")
            ws.send_json({"type": "confirm", "id": req2["id"], "decision": "deny"})
            _until(ws, "done")
        assert seen == [True, False]

    def test_always_allow_skips_next_prompt(self, client: TestClient, monkeypatch: Any) -> None:
        seen: list[bool] = []
        _install(monkeypatch, self._confirming_chat(seen))
        with client.websocket_connect("/ws/agent") as ws:
            ws.send_json({"message": "保存策略卡"})
            req = _until(ws, "confirm_required")
            ws.send_json({"type": "confirm", "id": req["id"], "decision": "always"})
            msgs = []
            while True:
                msg = ws.receive_json()
                msgs.append(msg["type"])
                if msg["type"] == "done":
                    break
            assert "confirm_required" not in msgs  # 第二次同名写操作不再询问
        assert seen == [True, True]

    def test_unknown_decision_counts_as_deny(self, client: TestClient, monkeypatch: Any) -> None:
        seen: list[bool] = []
        _install(monkeypatch, self._confirming_chat(seen))
        with client.websocket_connect("/ws/agent") as ws:
            ws.send_json({"message": "保存策略卡"})
            req = _until(ws, "confirm_required")
            ws.send_json({"type": "confirm", "id": req["id"], "decision": "yolo"})
            req2 = _until(ws, "confirm_required")
            ws.send_json({"type": "confirm", "id": req2["id"], "decision": "deny"})
            _until(ws, "done")
        assert seen == [False, False]

    def test_describe_write_fallbacks(self) -> None:
        assert describe_write("manage_watchlist", {"code": "600519"}) == "修改自选股：600519"
        assert describe_write("strategy_archive", {}) == "归档策略卡"
        assert describe_write("unknown_tool", {}) == "unknown_tool"


class TestCancel:
    def test_cancel_interrupts_turn_and_denies_pending_confirm(
        self, client: TestClient, monkeypatch: Any
    ) -> None:
        result: dict[str, Any] = {}

        def fake_chat(message: str, *args: Any, **kwargs: Any) -> SimpleNamespace:
            cb = kwargs["callbacks"]
            cb.on_chunk("第一部分")
            result["confirm"] = cb.on_confirm("manage_watchlist", {"code": "600519"})
            result["cancelled"] = cb.cancel_event.wait(5)
            return _resp("第一部分", interrupted=True)

        _install(monkeypatch, fake_chat)
        with client.websocket_connect("/ws/agent") as ws:
            ws.send_json({"message": "加自选"})
            _until(ws, "confirm_required")
            ws.send_json({"type": "cancel"})
            assert _until(ws, "interrupted") == {"type": "interrupted"}
            _until(ws, "done")
        assert result == {"confirm": False, "cancelled": True}

    def test_connection_stays_usable_after_cancel(
        self, client: TestClient, monkeypatch: Any
    ) -> None:
        gate = threading.Event()
        calls: list[str] = []

        def fake_chat(message: str, *args: Any, **kwargs: Any) -> SimpleNamespace:
            calls.append(message)
            cb = kwargs["callbacks"]
            if message == "慢":
                cb.cancel_event.wait(5)
                gate.set()
                return _resp("", interrupted=True)
            cb.on_chunk("快")
            return _resp("快")

        _install(monkeypatch, fake_chat)
        with client.websocket_connect("/ws/agent") as ws:
            ws.send_json({"message": "慢"})
            assert ws.receive_json() == {"type": "thinking"}
            ws.send_json({"type": "cancel"})
            _until(ws, "done")
            ws.send_json({"message": "快"})
            assert _until(ws, "chunk") == {"type": "chunk", "text": "快"}
            _until(ws, "done")
        assert gate.is_set()
        assert calls == ["慢", "快"]

    def test_control_messages_outside_turn_are_ignored(
        self, client: TestClient, monkeypatch: Any
    ) -> None:
        _install(monkeypatch, lambda *a, **k: _resp())
        with client.websocket_connect("/ws/agent") as ws:
            ws.send_json({"type": "cancel"})
            ws.send_json({"type": "confirm", "id": "c1", "decision": "allow"})
            ws.send_json({"message": "hi"})
            assert ws.receive_json() == {"type": "thinking"}


class TestStreamExtras:
    def test_thinking_retry_and_usage(self, client: TestClient, monkeypatch: Any) -> None:
        def fake_chat(message: str, *args: Any, **kwargs: Any) -> SimpleNamespace:
            cb = kwargs["callbacks"]
            cb.on_thinking("先看行情")
            cb.on_status("retry", {"attempt": 1, "max": 3})
            cb.on_chunk("答")
            cb.usage_out.update(prompt_tokens=1200, completion_tokens=300)
            return _resp("答")

        _install(monkeypatch, fake_chat)
        with client.websocket_connect("/ws/agent") as ws:
            ws.send_json({"message": "茅台"})
            assert ws.receive_json() == {"type": "thinking"}
            assert ws.receive_json() == {"type": "thinking_delta", "text": "先看行情"}
            assert ws.receive_json() == {"type": "retry", "attempt": 1, "max": 2}
            assert ws.receive_json() == {"type": "chunk", "text": "答"}
            assert ws.receive_json() == {
                "type": "usage",
                "prompt_tokens": 1200,
                "completion_tokens": 300,
                "total_tokens": 1500,
            }
            assert ws.receive_json()["type"] == "done"

    def test_no_usage_event_when_unknown(self, client: TestClient, monkeypatch: Any) -> None:
        def fake_chat(message: str, *args: Any, **kwargs: Any) -> SimpleNamespace:
            kwargs["callbacks"].on_chunk("答")
            return _resp("答")

        _install(monkeypatch, fake_chat)
        with client.websocket_connect("/ws/agent") as ws:
            ws.send_json({"message": "茅台"})
            assert [ws.receive_json()["type"] for _ in range(3)] == ["thinking", "chunk", "done"]


class TestSessionsEndpoint:
    def test_lists_sessions_newest_first(
        self, client: TestClient, monkeypatch: Any, tmp_path: Any
    ) -> None:
        from mommy_chaogu.agent.memory import ConversationMemory

        memory = ConversationMemory(tmp_path / "agent.db")
        memory.add("user", "茅台怎么样", session_id="tui-old")
        memory.add("assistant", "还行", session_id="tui-old")
        memory.add("user", "宁德时代和比亚迪对比", session_id="web-new")
        monkeypatch.setattr("mommy_chaogu.web.routes.agent.get_agent_memory", lambda: memory)

        body = client.get("/api/agent/sessions?limit=5").json()
        assert [s["session_id"] for s in body["sessions"]] == ["web-new", "tui-old"]
        assert body["sessions"][0]["preview"] == "宁德时代和比亚迪对比"
        assert body["sessions"][1]["messages"] == 2

    def test_storage_failure_returns_empty_list(self, client: TestClient, monkeypatch: Any) -> None:
        broken = MagicMock()
        broken.session.side_effect = RuntimeError("db locked")
        monkeypatch.setattr("mommy_chaogu.web.routes.agent.get_agent_memory", lambda: broken)
        assert client.get("/api/agent/sessions").json() == {"sessions": []}


class TestAgentInfo:
    def test_reports_provider_and_model_without_key(
        self, client: TestClient, monkeypatch: Any
    ) -> None:
        cfg = SimpleNamespace(
            agent=SimpleNamespace(provider="deepseek", model=None, api_key="sk-secret")
        )
        monkeypatch.setattr("mommy_chaogu.config.load_config", lambda: cfg)
        body = client.get("/api/agent/info").json()
        assert body == {"configured": True, "provider": "deepseek", "model": "deepseek-chat"}
        assert "sk-secret" not in str(body)

    def test_unconfigured(self, client: TestClient, monkeypatch: Any) -> None:
        cfg = SimpleNamespace(
            agent=SimpleNamespace(provider="deepseek", model="deepseek-reasoner", api_key="")
        )
        monkeypatch.setattr("mommy_chaogu.config.load_config", lambda: cfg)
        assert client.get("/api/agent/info").json()["configured"] is False

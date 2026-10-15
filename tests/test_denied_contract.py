"""DENIED 契约跨层一致性（P8，依赖 P2 的结构化拒绝标志）。

agent/service 拒绝写操作时回传两份同源表示：

- ``on_tool_result`` 的 digest = ``DENIAL_RESULT_MESSAGE``（宿主 UI 判
  denied 的依据，经 ``is_denial_result`` 这一唯一判定入口）；
- 回传 LLM 的 ``_DENIAL_RESULT`` JSON 带 ``"denied": true`` 结构化标志
  （供模型与 UI 用字段而非字符串等值识别拒绝）。

本文件钉死 Python 侧可测的同源性：web/routes/ws.py 的
``tool_call_finished.status`` 枚举、TUI（tui/app、tui/views/chat、
side_panel 渲染表）消费的都是 agent/service 的同一判定入口。

TS 侧边界（Python 测试不可达，显式声明）：web/src/App.vue 与
web/src/lib/agentSocket.ts 对 ``tool_call_finished.status`` 的消费
（'done' | 'denied' 之外按 failed 兜底）不在本套件射程内，由前端
vitest 的 ``web/src/lib/agentSocket.test.ts`` 覆盖；本套件不运行前端测试。
"""

from __future__ import annotations

import json

from mommy_chaogu.agent import service as agent_service
from mommy_chaogu.tui import app as tui_app
from mommy_chaogu.tui.views import chat as tui_chat
from mommy_chaogu.tui.widgets.side_panel import _LOOK
from mommy_chaogu.web.routes import ws


class TestStructuredDenialFlag:
    def test_denial_json_flag_matches_digest_message(self) -> None:
        """结构化标志的 error 字段与 digest 文案同源：UI 判 denied 不漏一侧。"""
        flag = json.loads(agent_service._DENIAL_RESULT)
        assert flag["denied"] is True
        assert flag["error"] == agent_service.DENIAL_RESULT_MESSAGE
        assert agent_service.is_denial_result(flag["error"]) is True


class TestWsFinishStatus:
    def test_status_enum_contains_denied(self) -> None:
        assert "denied" in ws.TOOL_FINISH_STATUSES

    def test_denial_digest_maps_to_denied_not_fail(self) -> None:
        assert ws.tool_finish_status(False, agent_service.DENIAL_RESULT_MESSAGE) == "denied"

    def test_success_and_failure_mappings(self) -> None:
        assert ws.tool_finish_status(True, "ok") == "done"
        assert ws.tool_finish_status(False, "RuntimeError: boom") == "fail"


class TestTuiConsumesBackendContract:
    def test_ws_and_tui_use_same_denial_predicate(self) -> None:
        """宿主 UI 不各自做字符串等值：ws / TUI 消费同一函数对象。"""
        assert ws.is_denial_result is agent_service.is_denial_result
        assert tui_app.is_denial_result is agent_service.is_denial_result
        assert tui_chat.is_denial_result is agent_service.is_denial_result

    def test_side_panel_renders_denied_status(self) -> None:
        """_LOOK 缺 denied 键时，拒绝会被兜底渲染成「完成」——静默错误。"""
        assert "denied" in _LOOK

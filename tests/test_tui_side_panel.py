"""右侧面板（妈咪 + 工具调用时间线）+ 设计稿主题 + / 命令菜单。

覆盖：
- 妈咪状态机：忙碌/工具姿势/失败/完成/中断/空闲/点一下（纯函数）
- 主题：设计稿 12 套 + 延续主题全部注册，旧名 / 中文别名可解析
- 时间线：agent 工具调用 → 运行中/完成/失败/已拒绝；工作流步骤同样进时间线；
  Esc 中断标为已中断；/clear 清空；/tools 开关；窄终端自动收起
- / 菜单：Enter 执行高亮项、需参数命令先补全、Esc 只关菜单
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from types import SimpleNamespace
from typing import Any

from mommy_chaogu.agent.service import DENIAL_RESULT_MESSAGE
from mommy_chaogu.tui.services.colors import (
    LIGHT_BG_THEMES,
    TEXTUAL_THEMES,
    THEMES,
    resolve_theme,
    textual_theme_name,
)
from mommy_chaogu.tui.services.mascot import FACES, LINES, mascot_state
from tests.test_tui_smoke import _wait_for

WIDE = (130, 40)


def _run(coro: Coroutine[Any, Any, None]) -> None:
    asyncio.run(coro)


def _resp(text: str = "好的", interrupted: bool = False) -> Any:
    return SimpleNamespace(text=text, tool_calls=[], rounds=1, usage={}, interrupted=interrupted)


# ---------------------------------------------------------------------------
# 妈咪状态机（纯函数）
# ---------------------------------------------------------------------------


class TestMascotState:
    def test_every_pose_has_face_and_line(self) -> None:
        assert set(FACES) == set(LINES)

    def test_idle_ready(self) -> None:
        s = mascot_state(busy=False, running=[])
        assert (s.pose, s.line) == ("hero", "嗨～我是妈咪！")

    def test_busy_without_tools_thinks(self) -> None:
        assert mascot_state(busy=True, running=[]).pose == "think"

    def test_tool_pose_and_parallel_count(self) -> None:
        s = mascot_state(busy=True, running=["get_bars", "get_quote"], running_for_s=1.25)
        assert s.pose == "up"
        assert s.line == "冲！ ×2"
        assert "get_bars · get_quote" in s.sub
        assert "1.2s" in s.sub

    def test_unknown_tool_defaults_to_research(self) -> None:
        assert mascot_state(busy=True, running=["strategy_list"]).pose == "research"

    def test_recent_failure_while_busy(self) -> None:
        s = mascot_state(busy=True, running=["get_quote"], event="fail", event_age_s=0.5)
        assert s.pose == "huh"
        assert (
            mascot_state(busy=True, running=["get_quote"], event="fail", event_age_s=3).pose == "up"
        )

    def test_win_stop_then_idle(self) -> None:
        assert mascot_state(busy=False, running=[], event="win", event_age_s=1).line == "赚到了！"
        assert mascot_state(busy=False, running=[], event="stop", event_age_s=1).line == "等等…"
        assert mascot_state(busy=False, running=[], event="win", event_age_s=10).pose == "hero"

    def test_coffee_then_sleep(self) -> None:
        assert mascot_state(busy=False, running=[], idle_s=45).pose == "coffee"
        assert mascot_state(busy=False, running=[], idle_s=120).pose == "sleep"

    def test_poke(self) -> None:
        s = mascot_state(busy=False, running=[], idle_s=120, poke_age_s=0.5)
        assert s.pose == "hero"
        assert "试试" in s.sub


# ---------------------------------------------------------------------------
# 主题
# ---------------------------------------------------------------------------


class TestDesignThemes:
    def test_design_themes_present(self) -> None:
        design = {
            "dark", "light", "tokyo-night", "catppuccin-mocha", "dracula", "nord",
            "gruvbox-dark", "one-dark", "github-light", "solarized-light",
            "catppuccin-latte", "rose-pine-dawn",
        }  # fmt: skip
        assert design <= set(THEMES)
        assert {
            "light",
            "github-light",
            "solarized-light",
            "catppuccin-latte",
            "rose-pine-dawn",
        } == set(LIGHT_BG_THEMES)

    def test_every_theme_has_textual_theme(self) -> None:
        registered = {t.name for t in TEXTUAL_THEMES}
        for theme in THEMES:
            assert textual_theme_name(theme) in registered

    def test_legacy_names_and_aliases_resolve(self) -> None:
        assert resolve_theme("solarized") == "solarized-light"
        assert resolve_theme("latte") == "catppuccin-latte"
        assert resolve_theme("atom") == "one-dark"
        assert resolve_theme("tokyo") == "tokyo-night"
        assert resolve_theme("github") == "github-dark"
        assert resolve_theme("极夜") == "nord"
        assert resolve_theme("Dracula") == "dracula"
        assert resolve_theme("nope") is None

    def test_slash_theme_by_name(self) -> None:
        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                app.run_slash("theme", "rose-pine-dawn")
                await pilot.pause()
                assert app.ui_theme == "rose-pine-dawn"
                assert app.theme == "mommy-rose-pine-dawn"

        _run(_test())


# ---------------------------------------------------------------------------
# 时间线（Pilot）
# ---------------------------------------------------------------------------


class _ScriptedAgent:
    """按脚本触发 on_tool_call / on_tool_result 的假 agent。"""

    def __init__(self, script: list[tuple[str, bool, str]], gate: threading.Event | None = None):
        self.script = script
        self.gate = gate

    def chat(self, message, history=None, callbacks=None):  # type: ignore[no-untyped-def]
        for name, ok, result in self.script:
            callbacks.on_tool_call(name, {"code": "600519"})
            if self.gate is not None:
                while not self.gate.wait(0.05):
                    if callbacks.cancel_event.is_set():
                        return _resp("", interrupted=True)
            callbacks.on_tool_result(name, ok, 420, result)
        return _resp("茅台最新报价 1680 元。")


def _app_with(agent: Any) -> Any:
    from mommy_chaogu.tui.app import MommyTuiApp
    from mommy_chaogu.tui.services.bootstrap import FakeServices

    services = FakeServices.create()
    services.agent._agent = agent
    services.agent.route = lambda text: None  # type: ignore[method-assign]
    services.agent.watch_background = lambda on_done: False  # type: ignore[method-assign]
    return MommyTuiApp(services=services)  # type: ignore[arg-type]


class TestTimeline:
    def test_agent_tools_enter_timeline(self) -> None:
        from mommy_chaogu.tui.views.chat import ChatView
        from mommy_chaogu.tui.widgets.side_panel import SidePanel, TimelineRow

        quote = '{"code": "600519", "name": "贵州茅台", "price": 1680.0, "change_pct": 0.5}'
        agent = _ScriptedAgent(
            [
                ("get_quote", True, quote),
                ("get_bars", False, "Error: 超时"),
                ("manage_watchlist", False, DENIAL_RESULT_MESSAGE),
            ]
        )

        async def _test() -> None:
            app = _app_with(agent)
            async with app.run_test(size=WIDE) as pilot:
                side = app.query_one(SidePanel)
                assert side.display
                chat = app.query_one(ChatView)
                app.handle_chat_message("茅台怎么样")
                assert await _wait_for(pilot, lambda: not chat._busy)
                statuses = [(e.name, e.status) for e in side.entries()]
                assert statuses == [
                    ("get_quote", "done"),
                    ("get_bars", "failed"),
                    ("manage_watchlist", "denied"),
                ]
                assert side.stats()["total"] == 3
                assert "超时" in side.entries()[1].summary
                # 轮次头 #1 + 用户问题
                heads = side.query(".tl-turn")
                assert len(heads) == 1
                assert "#1" in str(heads[0].content)  # type: ignore[attr-defined]
                # 点击展开详情（参数 / 结果）
                row = side.query(TimelineRow).first()
                row.toggle()
                await pilot.pause()
                rendered = row.render().plain
                assert "参数" in rendered and "600519" in rendered
                assert "贵州茅台" in rendered
                # 完成后妈咪：本轮有失败 → 不是「赚到了」以外的状态也可；至少不再忙碌
                assert not side._is_busy

        _run(_test())

    def test_interrupt_marks_running_cancelled(self) -> None:
        from mommy_chaogu.tui.views.chat import ChatView
        from mommy_chaogu.tui.widgets.side_panel import SidePanel

        gate = threading.Event()
        agent = _ScriptedAgent([("get_quote", True, "{}")], gate=gate)

        async def _test() -> None:
            app = _app_with(agent)
            async with app.run_test(size=WIDE) as pilot:
                side = app.query_one(SidePanel)
                chat = app.query_one(ChatView)
                app.handle_chat_message("茅台怎么样")
                assert await _wait_for(pilot, lambda: side.stats()["running"] == 1)
                chat.action_cancel_chat()
                await pilot.pause()
                assert side.entries()[0].status == "cancelled"
                assert await _wait_for(pilot, lambda: not chat._busy)
                gate.set()

        _run(_test())

    def test_workflow_steps_enter_timeline(self) -> None:
        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView
        from mommy_chaogu.tui.widgets.side_panel import SidePanel

        services = FakeServices.create()
        workflow = SimpleNamespace(
            description="早盘简报",
            steps=[
                SimpleNamespace(display_name="大盘指数"),
                SimpleNamespace(display_name="自选股"),
            ],
        )
        services.agent.route = lambda text: SimpleNamespace(matched=True, workflow=workflow)  # type: ignore[method-assign]

        def _execute(route, text, on_start, on_done, is_cancelled=None):  # type: ignore[no-untyped-def]
            for name, ok in (("大盘指数", True), ("自选股", False)):
                on_start(name)
                on_done(name, ok)
            return SimpleNamespace(summary="今天大盘偏强。", steps=[])

        services.agent.execute_workflow = _execute  # type: ignore[method-assign]

        async def _test() -> None:
            app = MommyTuiApp(services=services)  # type: ignore[arg-type]
            async with app.run_test(size=WIDE) as pilot:
                side = app.query_one(SidePanel)
                chat = app.query_one(ChatView)
                app.handle_chat_message("今天怎么样")
                assert await _wait_for(pilot, lambda: not chat._busy)
                assert await _wait_for(pilot, lambda: side.stats()["total"] == 2)
                assert [(e.name, e.status) for e in side.entries()] == [
                    ("大盘指数", "done"),
                    ("自选股", "failed"),
                ]

        _run(_test())

    def test_clear_empties_timeline(self) -> None:
        from mommy_chaogu.tui.views.chat import ChatView
        from mommy_chaogu.tui.widgets.side_panel import SidePanel

        async def _test() -> None:
            app = _app_with(_ScriptedAgent([("get_quote", True, "{}")]))
            async with app.run_test(size=WIDE) as pilot:
                side = app.query_one(SidePanel)
                chat = app.query_one(ChatView)
                app.handle_chat_message("茅台")
                assert await _wait_for(pilot, lambda: side.stats()["total"] == 1 and not chat._busy)
                app.run_slash("clear")
                assert await _wait_for(pilot, lambda: side.stats()["total"] == 0)
                assert len(side.query(".tl-turn")) == 0

        _run(_test())

    def test_tools_toggle_and_narrow_autohide(self) -> None:
        from mommy_chaogu.tui.widgets.side_panel import SidePanel

        async def _test() -> None:
            app = _app_with(None)
            async with app.run_test(size=WIDE) as pilot:
                side = app.query_one(SidePanel)
                assert side.display
                app.run_slash("tools")
                await pilot.pause()
                assert not side.display
                app.run_slash("tools")
                await pilot.pause()
                assert side.display
            narrow = _app_with(None)
            async with narrow.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                assert not narrow.query_one(SidePanel).display

        _run(_test())

    def test_status_line_tracks_session_tokens(self) -> None:
        from mommy_chaogu.tui.views.chat import ChatView
        from mommy_chaogu.tui.widgets.status_line import StatusLine

        class _Agent:
            def chat(self, message, history=None, callbacks=None):  # type: ignore[no-untyped-def]
                return SimpleNamespace(text="好", interrupted=False, usage={"total_tokens": 1234})

        async def _test() -> None:
            app = _app_with(_Agent())
            async with app.run_test(size=WIDE) as pilot:
                chat = app.query_one(ChatView)
                app.handle_chat_message("hi")
                assert await _wait_for(pilot, lambda: not chat._busy)
                await pilot.pause()
                assert "1,234 tokens" in str(app.query_one(StatusLine).content)

        _run(_test())


# ---------------------------------------------------------------------------
# / 命令菜单
# ---------------------------------------------------------------------------


class TestSlashMenu:
    def test_enter_runs_highlighted_command(self) -> None:
        from mommy_chaogu.tui.views.chat import ChatView
        from mommy_chaogu.tui.widgets.side_panel import SidePanel

        async def _test() -> None:
            app = _app_with(None)
            async with app.run_test(size=WIDE) as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt")
                prompt.value = "/too"  # type: ignore[attr-defined]
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                assert not app.query_one(SidePanel).display  # /tools 已执行
                assert prompt.value == ""  # type: ignore[attr-defined]

        _run(_test())

    def test_enter_on_arg_command_completes_first(self) -> None:
        from mommy_chaogu.tui.views.chat import ChatView

        async def _test() -> None:
            app = _app_with(None)
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt")
                prompt.value = "/quo"  # type: ignore[attr-defined]
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                assert prompt.value == "/quote "  # type: ignore[attr-defined]

        _run(_test())

    def test_escape_closes_menu_only(self) -> None:
        from mommy_chaogu.tui.views.chat import ChatView
        from mommy_chaogu.tui.widgets.hint_bar import HintBar

        async def _test() -> None:
            app = _app_with(None)
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt")
                prompt.value = "/t"  # type: ignore[attr-defined]
                await pilot.pause()
                hint = chat.query_one(HintBar)
                assert hint.mode == "suggestions"
                assert "<代码>" not in str(hint.content)
                await pilot.press("escape")
                await pilot.pause()
                assert hint.mode == "default"
                assert prompt.value == "/t"  # type: ignore[attr-defined]

        _run(_test())

    def test_menu_shows_arg_column(self) -> None:
        from mommy_chaogu.tui.views.chat import ChatView
        from mommy_chaogu.tui.widgets.hint_bar import HintBar

        async def _test() -> None:
            app = _app_with(None)
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                chat.query_one("#prompt").value = "/q"  # type: ignore[attr-defined]
                await pilot.pause()
                content = str(chat.query_one(HintBar).content)
                assert "/quote" in content and "<代码>" in content
                assert "enter 执行" in content

        _run(_test())

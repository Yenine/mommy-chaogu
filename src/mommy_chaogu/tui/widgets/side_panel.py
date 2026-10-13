"""SidePanel — 右侧面板：妈咪 + 工具调用时间线（设计稿右栏）。

    ┌────────────────────────────────────────┐
    │ (≧▽≦)↗  ╭ 冲！ ×2 ╮                    │  ← 妈咪：姿势/台词跟随 agent 活动
    │  ▁▃▅▇   ● get_quote · get_bars · 1.2s  │
    ├────────────────────────────────────────┤
    │ 工具调用时间线                      ✕  │
    │ 共 5  ✓ 3  ● 1  ✗ 1  ⊘ 0               │
    ├────────────────────────────────────────┤
    │ #2 对比宁德时代和比亚迪        14:32:05│
    │ ✓ get_quote             完成    642ms  │
    │ │ code: "300750"                       │
    │ │ ━━━━━━━──────────────────────────    │  ← 本轮内的起止位置
    └────────────────────────────────────────┘

数据由 app 在主线程推入（turn_started / tool_started / tool_finished …），
本组件不访问服务、不开线程。点击行展开开始时间 / 耗时 / 参数 / 结果。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Static

from mommy_chaogu.tui.services.colors import color, current_theme
from mommy_chaogu.tui.services.mascot import FACES, mascot_state

SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_TICK_S = 0.15
_POP_S = 0.35
_MAX_DETAIL_LINES = 10


def _c(role: str) -> str:
    return color(current_theme(), role)


def _dur(seconds: float) -> str:
    return f"{seconds * 1000:.0f}ms" if seconds < 1 else f"{seconds:.1f}s"


def _args_inline(args: dict[str, Any]) -> str:
    return ", ".join(
        f"{k}: {json.dumps(v, ensure_ascii=False, default=str)}" for k, v in args.items()
    )


@dataclass
class TimelineEntry:
    """一条工具调用（或工作流步骤）的时间线记录。"""

    key: str
    name: str
    args: dict[str, Any]
    turn: int
    start: float = field(default_factory=time.monotonic)
    started_at: datetime = field(default_factory=datetime.now)
    end: float | None = None
    status: str = "running"  # running / done / failed / denied / cancelled
    summary: str = ""
    result: str = ""

    def elapsed(self, now: float | None = None) -> float:
        return (self.end if self.end is not None else (now or time.monotonic())) - self.start


# status → (语义色角色, 图标, 标签)
_LOOK: dict[str, tuple[str, str, str]] = {
    "done": ("success", "✓", "完成"),
    "failed": ("danger", "✗", "失败"),
    "denied": ("warning", "⊘", "已拒绝"),
    "cancelled": ("faint", "⊘", "已中断"),
}


class TimelineRow(Widget, can_focus=True):
    """时间线中的一行；点击 / Enter 展开详情。"""

    DEFAULT_CSS = """
    TimelineRow { height: auto; padding: 0 1; }
    TimelineRow:hover { background: $panel; }
    TimelineRow.-open { background: $panel; }
    TimelineRow:focus { background: $panel; }
    """

    def __init__(self, entry: TimelineEntry, span: Callable[[int], tuple[float, float]]) -> None:
        super().__init__()
        self.entry = entry
        self._span = span
        self.tick = 0
        self.open = False

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.toggle()

    def on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.stop()
            self.toggle()

    def toggle(self) -> None:
        self.open = not self.open
        self.set_class(self.open, "-open")
        self.refresh(layout=True)

    def _look(self) -> tuple[str, str, str]:
        e = self.entry
        if e.status == "running":
            return _c("warning"), SPIN[self.tick % len(SPIN)], "运行中"
        role, icon, label = _LOOK.get(e.status, _LOOK["done"])
        return _c(role), icon, label

    def render(self) -> Text:
        e = self.entry
        width = max(self.size.width, 20)
        tone, icon, label = self._look()
        muted, faint = _c("muted"), _c("faint")
        dur = _dur(e.elapsed())
        right = f"{label} {dur:>6}"
        head = Text(no_wrap=True, overflow="ellipsis")
        head.append(f"{icon} ", style=tone)
        name_w = max(4, width - 2 - cell_len(right) - 1)
        name = Text(e.name, style="bold")
        name.truncate(name_w, overflow="ellipsis")
        head.append_text(name)
        head.append(" " * max(1, width - 2 - cell_len(name.plain) - cell_len(right)))
        head.append(label, style=tone).append(f" {dur:>6}", style=muted)

        rail = Text("│ ", style=faint)
        lines = [head]
        if e.args:
            args = rail.copy()
            args.append(_args_inline(e.args), style=muted)
            args.truncate(width, overflow="ellipsis")
            lines.append(args)
        if e.summary and e.status != "running":
            summ = rail.copy()
            summ.append(f"⎿ {e.summary}", style=_c("danger") if e.status == "failed" else muted)
            summ.truncate(width, overflow="ellipsis")
            lines.append(summ)
        lines.append(self._bar(width, tone, rail))
        if self.open:
            lines.extend(self._details(width, rail))
        return Text("\n").join(lines)

    def _bar(self, width: int, tone: str, rail: Text) -> Text:
        """本轮时间轴上的起止位置（━ 填充 / ─ 底轨）。"""
        e = self.entry
        a, b = self._span(e.turn)
        total = max(b - a, 1e-6)
        cols = max(width - 2, 4)
        end = e.end if e.end is not None else time.monotonic()
        left = int((e.start - a) / total * cols)
        fill = max(1, round((end - e.start) / total * cols))
        left = min(left, cols - 1)
        fill = min(fill, cols - left)
        bar = rail.copy()
        bar.append("─" * left, style=_c("track"))
        bar.append("━" * fill, style=tone)
        bar.append("─" * (cols - left - fill), style=_c("track"))
        return bar

    def _details(self, width: int, rail: Text) -> list[Text]:
        e = self.entry
        muted, info = _c("muted"), _c("info")
        out: list[Text] = []

        def kv(key: str, value: str, style: str = "") -> None:
            for i, chunk in enumerate(value.splitlines() or [""]):
                if len(out) >= _MAX_DETAIL_LINES + 3:
                    return
                t = rail.copy()
                t.append(f"{key if i == 0 else '':<4} ", style=muted)
                t.append(chunk, style=style)
                t.truncate(width, overflow="ellipsis")
                out.append(t)

        kv("开始", e.started_at.strftime("%H:%M:%S"))
        kv("耗时", _dur(e.elapsed()))
        if e.args:
            kv("参数", json.dumps(e.args, ensure_ascii=False, default=str), info)
        if e.status == "running":
            kv("结果", "运行中…", _c("warning"))
        else:
            res = (e.result or e.summary or "—").strip()
            lines = res.splitlines()
            if len(lines) > _MAX_DETAIL_LINES:
                lines = [*lines[:_MAX_DETAIL_LINES], f"… 共 {len(res.splitlines())} 行"]
            kv("结果", "\n".join(lines), _c("danger") if e.status == "failed" else "")
        return out


class _MascotFace(Static):
    """妈咪颜文字；点一下她会跳出来打招呼。"""

    def on_click(self, event: events.Click) -> None:
        event.stop()
        panel = next((a for a in self.ancestors if isinstance(a, SidePanel)), None)
        if panel is not None:
            panel.poke()


class _CloseButton(Static):
    def on_click(self, event: events.Click) -> None:
        event.stop()
        toggle = getattr(self.app, "action_toggle_tools", None)
        if callable(toggle):
            toggle()


class SidePanel(Vertical):
    """右侧面板：妈咪 + 工具调用时间线。"""

    DEFAULT_CSS = """
    SidePanel {
        width: 46;
        height: 1fr;
        background: $surface;
        border-left: solid $foreground 12%;
    }
    SidePanel #mascot {
        height: 5;
        padding: 0 1;
        border-bottom: solid $foreground 12%;
    }
    SidePanel #mascot-face { width: 12; height: 4; color: $accent; text-style: bold; }
    SidePanel #mascot-right { width: 1fr; height: 4; }
    SidePanel #mascot-bubble {
        width: auto;
        max-width: 100%;
        height: 3;
        border: round $foreground 30%;
        padding: 0 1;
        text-style: bold;
    }
    SidePanel #mascot-bubble.-pop { border: round $accent; }
    SidePanel #mascot-sub { height: 1; }
    SidePanel #tl-head {
        height: auto;
        padding: 0 1;
        border-bottom: solid $foreground 12%;
    }
    SidePanel #tl-title-row { height: 1; }
    SidePanel #tl-title { width: 1fr; text-style: bold; }
    SidePanel #tl-close { width: 2; color: $text-muted; }
    SidePanel #tl-close:hover { color: $text; }
    SidePanel #tl-stats { height: 1; margin-top: 1; }
    SidePanel #timeline { height: 1fr; scrollbar-size-vertical: 1; }
    SidePanel .tl-turn { height: 1; padding: 0 1; margin-top: 1; }
    SidePanel #tl-empty { padding: 1 1; }
    """

    def __init__(self, id: str = "side-panel") -> None:
        super().__init__(id=id)
        self._entries: dict[str, TimelineEntry] = {}
        self._rows: dict[str, TimelineRow] = {}
        self._turns: dict[int, tuple[str, datetime]] = {}
        self._turn_heads: set[int] = set()
        self._is_busy = False
        self._mascot_ev: tuple[str, float] | None = None
        self._last_active = time.monotonic()
        self._poked = -1e9
        self._tick_n = 0
        self._mascot_key: tuple[Any, ...] = ()
        self._pose = ""
        self._tick_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="mascot"):
            yield _MascotFace(id="mascot-face")
            with Vertical(id="mascot-right"):
                yield Static(id="mascot-bubble")
                yield Static(id="mascot-sub")
        with Vertical(id="tl-head"):
            with Horizontal(id="tl-title-row"):
                yield Static("工具调用时间线", id="tl-title")
                yield _CloseButton("✕", id="tl-close")
            yield Static(id="tl-stats")
        # 滚动容器本身不进焦点链：Tab 从输入框出来先回到对话流，
        # 时间线行（TimelineRow）仍可逐条聚焦、Enter 展开
        timeline = VerticalScroll(id="timeline")
        timeline.can_focus = False
        with timeline:
            yield Static("", id="tl-empty")

    def on_mount(self) -> None:
        self._refresh_stats()
        self._render_mascot(force=True)
        self._tick_timer = self.set_interval(_TICK_S, self._on_tick)

    # ------------------------------------------------------------------
    # 对外 API（app 主线程调用）
    # ------------------------------------------------------------------

    def turn_started(self, turn: int, label: str) -> None:
        """登记一轮（轮次头在该轮首个工具出现时才挂载）。"""
        self._turns[turn] = (label, datetime.now())

    def set_busy(self, busy: bool) -> None:
        self._is_busy = busy
        self._last_active = time.monotonic()
        self._render_mascot()

    def mascot_event(self, kind: str) -> None:
        """win / fail / stop：驱动妈咪的短暂反应。"""
        self._mascot_ev = (kind, time.monotonic())
        self._last_active = time.monotonic()
        self._render_mascot()

    def touch(self) -> None:
        """用户有输入：重置空闲计时（叫醒睡觉的妈咪）。"""
        was_idle = time.monotonic() - self._last_active > 30
        self._last_active = time.monotonic()
        if was_idle:
            self._render_mascot()

    def poke(self) -> None:
        self._poked = time.monotonic()
        self._last_active = self._poked
        self._render_mascot()

    def tool_started(self, key: str, name: str, args: dict[str, Any], turn: int) -> None:
        if key in self._entries:
            return
        timeline = self.query_one("#timeline", VerticalScroll)
        self._hide_empty()
        if turn not in self._turn_heads:
            self._turn_heads.add(turn)
            label, started = self._turns.get(turn, ("", datetime.now()))
            timeline.mount(Static(self._turn_text(turn, label, started), classes="tl-turn"))
        entry = TimelineEntry(key, name, dict(args or {}), turn)
        row = TimelineRow(entry, self._span)
        row.tick = self._tick_n
        self._entries[key] = entry
        self._rows[key] = row
        timeline.mount(row)
        timeline.scroll_end(animate=False)
        self._refresh_stats()
        self._render_mascot()

    def tool_finished(
        self,
        key: str,
        status: str,
        elapsed_ms: int | None = None,
        summary: str = "",
        result: str = "",
    ) -> None:
        entry = self._entries.get(key)
        if entry is None or entry.status != "running":
            return
        entry.end = entry.start + elapsed_ms / 1000 if elapsed_ms else time.monotonic()
        entry.status = status
        entry.summary = summary
        entry.result = result
        self._refresh_turn_rows(entry.turn)
        self._refresh_stats()
        if status == "failed":
            self.mascot_event("fail")
        else:
            self._render_mascot()

    def cancel_running(self) -> None:
        """中断：所有运行中的工具标为已中断。"""
        now = time.monotonic()
        for entry in self._entries.values():
            if entry.status == "running":
                entry.status, entry.end, entry.summary = "cancelled", now, "已被用户中断"
                self._rows[entry.key].refresh(layout=True)
        self._refresh_stats()

    async def clear(self) -> None:
        """/clear、切会话：清空时间线。"""
        self._entries.clear()
        self._rows.clear()
        self._turn_heads.clear()
        timeline = self.query_one("#timeline", VerticalScroll)
        await timeline.query("*").remove()
        await timeline.mount(Static("", id="tl-empty"))
        self._refresh_stats()
        self._render_mascot()

    def stats(self) -> dict[str, int]:
        counts = {"total": len(self._entries)}
        for st in ("running", "done", "failed", "denied", "cancelled"):
            counts[st] = sum(1 for e in self._entries.values() if e.status == st)
        return counts

    def entries(self) -> list[TimelineEntry]:
        return list(self._entries.values())

    def refresh_theme(self) -> None:
        """切主题后重绘 Python 侧着色的部分。"""
        self._refresh_stats()
        self._render_mascot(force=True)
        for heading in self.query(".tl-turn"):
            heading.refresh()
        for row in self._rows.values():
            row.refresh()
        self._repaint_turn_heads()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _span(self, turn: int) -> tuple[float, float]:
        now = time.monotonic()
        es = [e for e in self._entries.values() if e.turn == turn]
        if not es:
            return now, now
        return min(e.start for e in es), max(e.end if e.end is not None else now for e in es)

    def _refresh_turn_rows(self, turn: int) -> None:
        for row in self._rows.values():
            if row.entry.turn == turn:
                row.refresh(layout=True)

    def _turn_text(self, turn: int, label: str, started: datetime) -> Text:
        t = Text(no_wrap=True, overflow="ellipsis")
        t.append(f"#{turn} ", style=_c("info"))
        width = max(self.size.width - 2, 30)
        clock = started.strftime("%H:%M:%S")
        room = max(4, width - cell_len(f"#{turn} ") - cell_len(clock) - 1)
        lab = Text(" ".join(label.split()), style=_c("muted"))
        lab.truncate(room, overflow="ellipsis")
        t.append_text(lab)
        t.append(" " * max(1, room - cell_len(lab.plain) + 1))
        t.append(clock, style=_c("muted"))
        return t

    def _repaint_turn_heads(self) -> None:
        heads = list(self.query(".tl-turn").results(Static))
        for turn, head in zip(sorted(self._turn_heads), heads, strict=False):
            label, started = self._turns.get(turn, ("", datetime.now()))
            head.update(self._turn_text(turn, label, started))

    def _hide_empty(self) -> None:
        for w in self.query("#tl-empty"):
            w.remove()

    def _refresh_stats(self) -> None:
        s = self.stats()
        t = Text(no_wrap=True)
        muted = _c("muted")
        t.append("共 ", style=muted).append(str(s["total"]), style="bold").append("   ")
        t.append("✓", style=_c("success")).append(f" {s['done']}   ", style=muted)
        t.append("●", style=_c("warning")).append(f" {s['running']}   ", style=muted)
        t.append("✗", style=_c("danger")).append(f" {s['failed']}   ", style=muted)
        t.append("⊘", style=_c("faint")).append(f" {s['denied'] + s['cancelled']}", style=muted)
        try:
            self.query_one("#tl-stats", Static).update(t)
            empty = self.query("#tl-empty")
            if empty:
                empty.first(Static).update(Text("暂无工具调用", style=_c("faint")))
        except Exception:
            return

    def _running_entries(self) -> list[TimelineEntry]:
        return [e for e in self._entries.values() if e.status == "running"]

    def _on_tick(self) -> None:
        self._tick_n += 1
        for entry in self._running_entries():
            row = self._rows[entry.key]
            row.tick = self._tick_n
            row.refresh()
            for other in self._rows.values():  # 运行中会拉长本轮时间轴
                if other is not row and other.entry.turn == entry.turn:
                    other.refresh()
        self._render_mascot()

    def _render_mascot(self, force: bool = False) -> None:
        now = time.monotonic()
        running = self._running_entries()
        kind, at = self._mascot_ev or (None, 0.0)
        state = mascot_state(
            busy=self._is_busy,
            running=[e.name for e in running],
            running_for_s=now - min((e.start for e in running), default=now),
            event=kind,
            event_age_s=now - at,
            idle_s=now - self._last_active,
            poke_age_s=now - self._poked,
        )
        sleepy = state.pose in ("sleep", "coffee", "wait")
        period = 0.0 if sleepy else (0.45 if self._is_busy else 0.9)
        phase = int(now / period) % 2 if period else 0
        key = (state, phase, current_theme())
        if key == self._mascot_key and not force:
            return
        self._mascot_key = key
        try:
            face = self.query_one("#mascot-face", Static)
            bubble = self.query_one("#mascot-bubble", Static)
            sub = self.query_one("#mascot-sub", Static)
        except Exception:
            return
        top, prop = FACES[state.pose]
        face.update("\n".join(["", top, prop] if phase == 0 else [top, prop, ""]))
        bubble.update(state.line)
        dot = Text("● ", style=_c(state.tone))
        dot.append(state.sub, style=_c("muted"))
        dot.truncate(max(sub.size.width, 10), overflow="ellipsis")
        sub.update(dot)
        if state.pose != self._pose:
            self._pose = state.pose
            bubble.add_class("-pop")
            self.set_timer(_POP_S, lambda: bubble.remove_class("-pop"))

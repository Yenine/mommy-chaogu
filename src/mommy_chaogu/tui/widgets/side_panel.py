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
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Static

from mommy_chaogu.market_data.time_utils import TZ_BEIJING
from mommy_chaogu.tui.services import images
from mommy_chaogu.tui.services.colors import color, current_theme
from mommy_chaogu.tui.services.formatting import format_elapsed
from mommy_chaogu.tui.services.mascot import FACES, mascot_state

SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_TICK_S = 0.15
_POP_S = 0.35
_MAX_DETAIL_LINES = 10


def _now() -> datetime:
    # 与顶栏时钟同一时区（A 股交易时间），避免顶栏 10:12、时间线 02:12 的错位
    return datetime.now(TZ_BEIJING)


# 时间线最多保留的轮次（更早的轮次连同行一起移除，长会话不无限增长）
MAX_TURNS = 30


def _c(role: str) -> str:
    return color(current_theme(), role)


def _dur(seconds: float) -> str:
    return format_elapsed(int(seconds * 1000))


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
    started_at: datetime = field(default_factory=_now)
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


def _wrap_cells(text: str, width: int) -> list[str]:
    """按终端单元格宽度切行（中文占 2 格）。"""
    if not text:
        return [""]
    lines: list[str] = []
    cur, cur_w = "", 0
    for ch in text:
        w = cell_len(ch)
        if cur and cur_w + w > width:
            lines.append(cur)
            cur, cur_w = "", 0
        cur += ch
        cur_w += w
    lines.append(cur)
    return lines


class TimelineRow(Widget, can_focus=True):
    """时间线中的一行；点击 / Enter 展开详情。"""

    DEFAULT_CSS = """
    TimelineRow { height: auto; padding: 0 1; margin-bottom: 1; }
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

        label_w = cell_len(rail.plain) + 5  # 「│ 」+「参数 」
        value_w = max(8, width - label_w)

        def kv(key: str, value: str, style: str = "") -> None:
            """键值行；长值按单元格宽度折行（设计稿 pre-wrap），不截断。"""
            chunks = [
                c for line in (value.splitlines() or [""]) for c in _wrap_cells(line, value_w)
            ]
            for i, chunk in enumerate(chunks):
                if len(out) >= _MAX_DETAIL_LINES * 2 + 3:
                    t = rail.copy().append("     …", style=muted)
                    out.append(t)
                    return
                t = rail.copy()
                t.append(f"{key if i == 0 else '':<4} ", style=muted)
                t.append(chunk, style=style)
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


class TimelineTurnHead(Widget):
    """轮次标题：#N 用户问题 … 时间（按自身实际宽度排版，滚动条出现也不截时间）。"""

    DEFAULT_CSS = """
    TimelineTurnHead { height: 1; padding: 0 1; margin-top: 1; }
    """

    def __init__(self, turn: int, label: str, started: datetime) -> None:
        super().__init__(classes="tl-turn")
        self.turn = turn
        self.label = " ".join(label.split())
        self.started = started

    def render(self) -> Text:
        width = max(self.size.width, 20)
        num = f"#{self.turn} "
        clock = self.started.strftime("%H:%M:%S")
        room = max(1, width - cell_len(num) - cell_len(clock) - 1)
        lab = Text(self.label, style=_c("muted"))
        lab.truncate(room, overflow="ellipsis")
        t = Text(no_wrap=True)
        t.append(num, style=_c("info")).append_text(lab)
        t.append(" " * max(1, width - cell_len(num) - cell_len(lab.plain) - cell_len(clock)))
        t.append(clock, style=_c("muted"))
        return t


class _MascotFace(Container):
    """妈咪：支持图片协议的终端显示立绘，否则颜文字；点一下她会跳出来打招呼。"""

    def __init__(self, id: str) -> None:
        super().__init__(id=id)
        self.use_image = images.supported()

    def compose(self) -> ComposeResult:
        if self.use_image:
            from textual_image.widget import Image

            yield Image(images.asset(images.POSE_IMAGES["hero"]), id="mascot-img")
        else:
            yield Static(id="mascot-text")

    def show(self, pose: str, kaomoji: str) -> None:
        if self.use_image:
            img: Any = self.query_one("#mascot-img")
            path = images.asset(images.POSE_IMAGES[pose])
            if img.image != path:
                img.image = path
        else:
            self.query_one("#mascot-text", Static).update(kaomoji)

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
        height: 6;
        padding: 1 1 0 2;
        border-bottom: solid $foreground 12%;
    }
    SidePanel #mascot.-image { height: 9; }
    SidePanel #mascot-face { width: 12; height: 100%; }
    SidePanel #mascot.-image #mascot-face { width: 14; }
    SidePanel #mascot-img { width: auto; height: 7; }
    SidePanel #mascot-text { color: $accent; text-style: bold; }
    SidePanel #mascot-right { width: 1fr; height: 100%; align-vertical: bottom; padding-left: 1; }
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
    SidePanel #tl-empty { padding: 1 1; }
    """

    def __init__(self, id: str = "side-panel") -> None:
        super().__init__(id=id)
        self._entries: dict[str, TimelineEntry] = {}
        self._rows: dict[str, TimelineRow] = {}
        self._by_turn: dict[int, list[TimelineEntry]] = {}
        self._heads: dict[int, TimelineTurnHead] = {}
        self._turns: dict[int, tuple[str, datetime]] = {}
        # 已全部收尾的轮次时间轴不再变化：缓存起止，避免每帧重扫
        self._span_cache: dict[int, tuple[float, float]] = {}
        self._current_turn: int | None = None
        self._is_busy = False
        self._mascot_ev: tuple[str, float] | None = None
        self._last_active = time.monotonic()
        self._poked = -1e9
        self._tick_n = 0
        self._mascot_key: tuple[Any, ...] = ()
        self._pose = ""
        self._tick_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="mascot", classes="-image" if images.supported() else ""):
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

    def on_show(self) -> None:
        """从隐藏恢复显示：隐藏期间跳过的刷新一次补齐。"""
        self.refresh_theme()

    # ------------------------------------------------------------------
    # 对外 API（app 主线程调用）
    # ------------------------------------------------------------------

    def turn_started(self, turn: int, label: str) -> None:
        """登记一轮（轮次头在该轮首个工具出现时才挂载）。"""
        self._turns[turn] = (label, _now())
        self._current_turn = turn

    def set_busy(self, busy: bool) -> None:
        self._is_busy = busy
        self._last_active = time.monotonic()
        if busy:
            self._mascot_ev = None  # 新一轮开始：上一轮的完成/失败/中断反应作废
        else:
            # 轮次已收尾仍在「运行中」的条目（如工作流中途抛异常）不能永远转圈
            self.settle_running("cancelled", "本轮结束时未完成")
            if self._mascot_ev is not None and self._mascot_ev[0] == "stop":
                # Esc 后 worker 迟迟才收尾：从真正停下的时刻起再展示「等等…」
                self._mascot_ev = ("stop", time.monotonic())
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
        if turn not in self._heads:
            label, started = self._turns.get(turn, ("", _now()))
            head = TimelineTurnHead(turn, label, started)
            self._heads[turn] = head
            self._by_turn[turn] = []
            timeline.mount(head)
            self._trim_old_turns()
        entry = TimelineEntry(key, name, dict(args or {}), turn)
        row = TimelineRow(entry, self._span)
        row.tick = self._tick_n
        self._entries[key] = entry
        self._rows[key] = row
        self._by_turn[turn].append(entry)
        self._span_cache.pop(turn, None)
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
        self._span_cache.pop(entry.turn, None)
        self._refresh_turn_rows(entry.turn)
        self._refresh_stats()
        if status == "failed":
            self.mascot_event("fail")
        else:
            self._render_mascot()

    def cancel_running(self) -> None:
        """中断：所有运行中的工具标为已中断。"""
        self.settle_running("cancelled", "已被用户中断")

    def settle_running(self, status: str, summary: str) -> None:
        """把仍在运行中的条目一次性落定（中断 / 出错 / 轮次收尾）。"""
        now = time.monotonic()
        touched: set[int] = set()
        for entry in self._entries.values():
            if entry.status == "running":
                entry.status, entry.end, entry.summary = status, now, summary
                touched.add(entry.turn)
        for turn in touched:
            self._span_cache.pop(turn, None)
            self._refresh_turn_rows(turn)
        if touched:
            self._refresh_stats()

    async def clear(self) -> None:
        """/clear、切会话：清空时间线，妈咪回到就绪。"""
        self._entries.clear()
        self._rows.clear()
        self._by_turn.clear()
        self._heads.clear()
        self._span_cache.clear()
        self._is_busy = False
        self._mascot_ev = None
        timeline = self.query_one("#timeline", VerticalScroll)
        await timeline.query("*").remove()
        await timeline.mount(Static("", id="tl-empty"))
        self._refresh_stats()
        self._render_mascot(force=True)

    def stats(self) -> dict[str, int]:
        counts = {"total": len(self._entries)}
        for st in ("running", "done", "failed", "denied", "cancelled"):
            counts[st] = sum(1 for e in self._entries.values() if e.status == st)
        return counts

    def entries(self) -> list[TimelineEntry]:
        return list(self._entries.values())

    def refresh_theme(self) -> None:
        """切主题 / 重新显示后重绘 Python 侧着色的部分。"""
        self._refresh_stats()
        self._render_mascot(force=True)
        for head in self._heads.values():
            head.refresh()
        for row in self._rows.values():
            row.refresh()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _span(self, turn: int) -> tuple[float, float]:
        cached = self._span_cache.get(turn)
        if cached is not None:
            return cached
        now = time.monotonic()
        es = self._by_turn.get(turn, [])
        if not es:
            return now, now
        span = (min(e.start for e in es), max(e.end if e.end is not None else now for e in es))
        if all(e.status != "running" for e in es):
            self._span_cache[turn] = span
        return span

    def _refresh_turn_rows(self, turn: int) -> None:
        for entry in self._by_turn.get(turn, []):
            self._rows[entry.key].refresh(layout=True)

    def _trim_old_turns(self) -> None:
        """超过 MAX_TURNS 的最早轮次连同其行一起移除。"""
        while len(self._heads) > MAX_TURNS:
            oldest = min(self._heads)
            self._heads.pop(oldest).remove()
            for entry in self._by_turn.pop(oldest, []):
                self._entries.pop(entry.key, None)
                row = self._rows.pop(entry.key, None)
                if row is not None:
                    row.remove()
            self._span_cache.pop(oldest, None)
            self._turns.pop(oldest, None)

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
        """当前轮仍在运行的条目（只看当前轮，旧轮遗留不会混进妈咪的台词）。"""
        if self._current_turn is None:
            return []
        return [e for e in self._by_turn.get(self._current_turn, []) if e.status == "running"]

    def _on_tick(self) -> None:
        if not self.display:
            return  # 隐藏时不做任何渲染；on_show 时一次补齐
        self._tick_n += 1
        if self._current_turn is not None and self._running_entries():
            for entry in self._by_turn.get(self._current_turn, []):
                row = self._rows[entry.key]
                row.tick = self._tick_n
                row.refresh()  # 运行中会拉长本轮时间轴，同轮各行都要重画
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
            face = self.query_one("#mascot-face", _MascotFace)
            bubble = self.query_one("#mascot-bubble", Static)
            sub = self.query_one("#mascot-sub", Static)
        except Exception:
            return
        top, prop = FACES[state.pose]
        face.show(state.pose, "\n".join(["", top, prop] if phase == 0 else [top, prop, ""]))
        bubble.update(state.line)
        dot = Text("● ", style=_c(state.tone))
        dot.append(state.sub, style=_c("muted"))
        dot.truncate(max(sub.size.width, 10), overflow="ellipsis")
        sub.update(dot)
        if state.pose != self._pose:
            self._pose = state.pose
            bubble.add_class("-pop")
            self.set_timer(_POP_S, lambda: bubble.remove_class("-pop"))

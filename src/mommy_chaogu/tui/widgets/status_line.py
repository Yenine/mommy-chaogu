"""StatusLine — 输入框下方的常驻状态行（设计稿底栏，取代 Footer）。

⏵⏵ 只读工具自动执行 · / 命令 · @ 股票 · ↑ 历史 · esc 中断      12,480 tokens · ctrl+p 面板
⏵⏵ 工作中 · esc 中断 · enter 排队（已排队 1 条）               12,480 tokens · ctrl+p 面板
"""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text
from textual.widgets import Static

from mommy_chaogu.tui.services.colors import color, current_theme


class StatusLine(Static):
    """左：模式 + 快捷键；右：本会话 token + 全局快捷键。"""

    DEFAULT_CSS = """
    StatusLine { height: 1; padding: 0 2; }
    """

    def __init__(self) -> None:
        super().__init__(id="status-line")
        self._busy = False
        self._queued = 0
        self._tokens = 0

    def on_mount(self) -> None:
        self._paint()

    def on_resize(self) -> None:
        self._paint()

    def set_busy(self, busy: bool, queued: int = 0) -> None:
        self._busy, self._queued = busy, queued
        self._paint()

    def set_tokens(self, total: int) -> None:
        self._tokens = max(0, int(total))
        self._paint()

    def refresh_theme(self) -> None:
        self._paint()

    def _paint(self) -> None:
        theme = current_theme()
        muted, faint = color(theme, "muted"), color(theme, "faint")
        left = Text(no_wrap=True, overflow="ellipsis")
        if self._busy:
            left.append("⏵⏵ 工作中", style=color(theme, "warning"))
            left.append(" · esc 中断 · enter 排队", style=faint)
            if self._queued:
                left.append(f"（已排队 {self._queued} 条）", style=faint)
        else:
            left.append("⏵⏵ 只读工具自动执行", style=muted)
            left.append(" · / 命令 · @ 股票 · ↑ 历史 · esc 中断", style=faint)
        right = Text(no_wrap=True)
        right.append(f"{self._tokens:,} tokens", style=muted)
        right.append(" · ctrl+p 面板 · ctrl+t 主题", style=faint)
        width = self.content_size.width or 100
        gap = width - cell_len(left.plain) - cell_len(right.plain)
        if gap < 2:
            left.truncate(max(10, width - cell_len(right.plain) - 2), overflow="ellipsis")
            gap = max(2, width - cell_len(left.plain) - cell_len(right.plain))
        self.update(Text.assemble(left, " " * gap, right))

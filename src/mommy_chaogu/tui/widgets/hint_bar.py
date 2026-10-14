"""HintBar — 输入框上方的上下文浮层（设计稿 / 命令菜单）。

状态：
  空闲 / busy:  隐藏（常驻快捷键见输入框下方 StatusLine）
  slash:       命令菜单（命令 · 参数 · 说明三列，高亮项 = Enter/Tab 接受的那条）
  @联想:       股票候选菜单（高亮项 = Tab/Enter 插入的代码）
  6 位代码:    ⏎ 查看 600519 报价
  确认:        ⏸ 等待确认 · y 允许 · n 拒绝 · a 本会话不再询问
"""

from __future__ import annotations

from collections.abc import Sequence

from rich.cells import cell_len
from rich.markup import escape
from textual.widgets import Static

from mommy_chaogu.tui.services.colors import color, current_theme

_MAX_SUGGESTIONS = 8
_CMD_W = 14
_ARG_W = 12


def _pad(text: str, width: int) -> str:
    return text + " " * max(1, width - cell_len(text))


def _window(n: int, selected: int) -> range:
    start = min(max(0, selected - _MAX_SUGGESTIONS + 1), max(0, n - _MAX_SUGGESTIONS))
    return range(start, min(n, start + _MAX_SUGGESTIONS))


class HintBar(Static):
    """输入框上方浮层：slash 菜单 / @ 候选 / 单行提示；空闲时隐藏。"""

    def __init__(self) -> None:
        super().__init__(classes="hint-bar")
        self._mode = "default"

    def _c(self, role: str) -> str:
        return color(current_theme(), role)

    def _set_mode(self, mode: str, body: str) -> None:
        self._mode = mode
        self.set_class(mode in ("suggestions", "stock-suggestions"), "-menu")
        self.set_class(mode in ("default", "busy"), "-idle")
        self.update(body)

    def on_mount(self) -> None:
        self.show_default()

    def show_default(self) -> None:
        self._set_mode(
            "default", f"[{self._c('muted')}] / 命令 · @ 股票 · Enter 发送 · ↑ 历史 · Esc 中断[/]"
        )

    def show_busy(self) -> None:
        self._set_mode("busy", f"[{self._c('muted')}] Esc 中断 · Enter 排队[/]")

    def _footer(self, total: int, shown: range) -> str:
        more = f"  {shown.start + 1}-{shown.stop}/{total}" if total > len(shown) else ""
        return f"[{self._c('faint')}]↑↓ 选择 · tab 补全 · enter 执行 · esc 关闭{more}[/]"

    def show_suggestions(
        self, matches: Sequence[tuple[str, str] | tuple[str, str, str]], selected: int = 0
    ) -> None:
        """slash 输入时展示命令菜单（name, description[, arg]），高亮选中项。"""
        lines: list[str] = []
        shown = _window(len(matches), selected)
        for i in shown:
            name, desc, *rest = matches[i]
            arg = rest[0] if rest else ""
            cmd = _pad(f"/{name}", _CMD_W)
            arg_col = _pad(arg, _ARG_W)
            if i == selected:
                lines.append(
                    f"[bold {self._c('accent')}]{escape(cmd)}[/][{self._c('muted')}]{escape(arg_col)}[/]"
                    f"[{self._c('accent')}]{escape(desc)}[/]"
                )
            else:
                lines.append(
                    f"[bold]{escape(cmd)}[/][{self._c('muted')}]{escape(arg_col)}[/]{escape(desc)}"
                )
        lines.append(self._footer(len(matches), shown))
        self._set_mode("suggestions", "\n".join(lines))

    def show_stock_suggestions(self, matches: list[tuple[str, str]], selected: int = 0) -> None:
        """@ 输入时展示股票候选（code, name 列表），高亮选中项。"""
        lines: list[str] = []
        shown = _window(len(matches), selected)
        for i in shown:
            code, name = matches[i]
            row = f"{escape(_pad(code, 10))}{escape(name)}"
            if i == selected:
                lines.append(f"[bold {self._c('accent')}]{row}[/]")
            else:
                lines.append(row)
        lines.append(self._footer(len(matches), shown))
        self._set_mode("stock-suggestions", "\n".join(lines))

    def show_code_hint(self, code: str) -> None:
        """输入完整 6 位代码时提示 Enter 直接看报价。"""
        self._set_mode("code-hint", f"[{self._c('muted')}] ⏎ 查看 {escape(code)} 报价[/]")

    def show_confirm(self) -> None:
        """写操作确认条等待决定时的按键提示。"""
        self._set_mode(
            "confirm",
            f"[{self._c('warning')}]⏸ 等待确认[/][{self._c('muted')}] · y 允许 · n 拒绝 · a 本会话不再询问[/]",
        )

    @property
    def mode(self) -> str:
        return self._mode

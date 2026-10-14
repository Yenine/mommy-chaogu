"""TopBar widget — 设计稿顶栏（两行：左品牌 + 工作目录，右模型 / 数据源 / 状态）。

    妈咪炒股↗  ~/research                    模型 deepseek-chat · 数据源 东方财富
    AI 投研 Agent        上证 3,847.51 ▲ +0.60% · AI🟢 deepseek · ∑ 1.2k tok · 14:32:05

Logo 头像在顶栏左侧的 LogoMark 里（支持图片协议的终端显示真图，否则颜文字）。

启动即知 agent 是否可用（不再只记日志）。指数快照由 app 的后台 worker
周期性喂入（set_index）；AI 状态在启动时按 AgentBridge.provider_name 设置。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from rich.cells import cell_len
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Static

from mommy_chaogu.tui.services import images
from mommy_chaogu.tui.services.colors import color
from mommy_chaogu.tui.services.formatting import (
    change_arrow,
    change_color,
    format_change_pct,
    format_tokens_compact,
    short_cwd,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def market_phase() -> str:
    """判断当前市场阶段（Asia/Shanghai 时区）。"""
    now = datetime.now(_SHANGHAI)
    h, m = now.hour, now.minute
    wd = now.weekday()
    if wd >= 5:
        return "已收盘"
    hm = h * 60 + m
    if 555 <= hm < 565:  # 9:15-9:25
        return "集合竞价"
    if 570 <= hm < 690 or 780 <= hm < 900:  # 9:30-11:30, 13:00-15:00
        return "交易中"
    if 690 <= hm < 780:  # 11:30-13:00
        return "午休"
    return "已收盘"


class LogoMark(Horizontal):
    """顶栏左侧的妈咪头像：图片协议终端显示 logo_face.png，否则颜文字。"""

    DEFAULT_CSS = """
    LogoMark { width: 7; height: 2; padding: 0 1 0 1; }
    LogoMark #logo-img { width: 5; height: 2; }
    LogoMark #logo-text { width: 5; height: 2; content-align: left middle; color: $accent; text-style: bold; }
    """

    def compose(self) -> ComposeResult:
        if images.supported():
            from textual_image.widget import Image

            yield Image(images.asset(images.LOGO_IMAGE), id="logo-img")
        else:
            yield Static("◕‿◕", id="logo-text")


class TopBar(Static):
    """顶部状态栏：品牌 · 工作目录 · 模型 · 数据源 · 指数 · AI 状态 · 用量 · 时间。"""

    ai_label: reactive[str] = reactive("AI⚪ 未配置")

    def __init__(self) -> None:
        super().__init__()
        self._clock = ""
        self._index: dict[str, Any] | None = None
        self._theme = "dark"
        self._session_tokens = 0
        self._model = ""
        self._source = ""
        self._cwd = short_cwd()

    def on_mount(self) -> None:
        self.set_interval(1.0, self._tick)

    def on_resize(self) -> None:
        self._refresh_display()

    def _tick(self) -> None:
        self._clock = datetime.now(_SHANGHAI).strftime("%H:%M:%S")
        self._refresh_display()

    def watch_ai_label(self, _label: str) -> None:
        self._refresh_display()

    def set_index(self, name: str, price: Any, change_pct: Any) -> None:
        """喂入指数快照（app 的 worker 线程经 call_from_thread 调用）。"""
        self._index = {"name": name, "price": price, "change_pct": change_pct}
        self._refresh_display()

    def set_model(self, model: str) -> None:
        """喂入当前模型名（AI 已配置时显示在右上）。"""
        self._model = model or ""
        self._refresh_display()

    def set_source(self, source: str) -> None:
        """喂入行情数据源标签（DataService.source_label）。"""
        self._source = source or ""
        self._refresh_display()

    def set_session_usage(self, total_tokens: int) -> None:
        """喂入本会话累计 token（app 在每轮结束后调用）。0 时不占位。"""
        self._session_tokens = max(0, int(total_tokens))
        self._refresh_display()

    def set_theme(self, theme: str) -> None:
        """主题切换后重渲染品牌色与涨跌颜色。"""
        self._theme = theme
        self._refresh_display()

    def _index_text(self) -> str:
        if self._index is None:
            return "[dim]指数 —[/]"
        name = str(self._index.get("name", ""))
        short = name.replace("指数", "")[:2] if name else "指数"
        price = self._index.get("price")
        price_str = f"{float(price):,.2f}" if price is not None else "—"
        pct = self._index.get("change_pct")
        color_ = change_color(pct, self._theme)
        change_str = f"{change_arrow(pct)} {format_change_pct(pct)}"
        return f"{short} {price_str} [{color_}]{change_str}[/{color_}]"

    @staticmethod
    def _row(left: Text, right: Text, width: int) -> Text:
        gap = width - cell_len(left.plain) - cell_len(right.plain)
        if gap < 2:
            left.truncate(max(8, width - cell_len(right.plain) - 2), overflow="ellipsis")
            gap = max(2, width - cell_len(left.plain) - cell_len(right.plain))
        return Text.assemble(left, " " * gap, right)

    def _refresh_display(self) -> None:
        accent = color(self._theme, "accent")
        muted = color(self._theme, "muted")
        width = self.content_size.width or 120

        brand = Text.from_markup(f"[bold]妈咪炒股[/][bold {accent}]↗[/]  [{muted}]{self._cwd}[/]")
        info: list[str] = []
        if self._model:
            info.append(f"模型 {self._model}")
        if self._source:
            info.append(f"数据源 {self._source}")
        top_right = Text(" · ".join(info), style=muted)

        tagline = Text("AI 投研 Agent", style=f"italic {muted}")
        parts = [self._index_text(), self.ai_label]
        if self._session_tokens > 0:
            parts.append(f"[dim]∑ {format_tokens_compact(self._session_tokens)} tok[/]")
        if self._clock:
            parts.append(f"[dim]{self._clock}[/]")
        status = Text.from_markup(" [dim]·[/] ".join(parts))

        self.update(
            Text("\n").join([self._row(brand, top_right, width), self._row(tagline, status, width)])
        )

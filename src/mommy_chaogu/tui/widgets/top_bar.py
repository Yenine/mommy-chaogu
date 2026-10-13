"""TopBar widget — 品牌 + 指数快照 + AI 状态点 + 会话用量 + 时钟（设计稿顶栏）。

    ◕‿◕ 妈咪炒股↗ AI 投研 Agent │ 上证 3,847.51 ▲0.6% · AI🟢 deepseek deepseek-chat · ∑ 1.2k tok · 14:32:05
    ◕‿◕ 妈咪炒股↗ AI 投研 Agent │ 指数 — · AI⚪ 未配置 · 14:32:05

启动即知 agent 是否可用（不再只记日志）。指数快照由 app 的后台 worker
周期性喂入（set_index）；AI 状态在启动时按 AgentBridge.provider_name 设置。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from rich.markup import escape
from textual.reactive import reactive
from textual.widgets import Static

from mommy_chaogu.tui.services.colors import color
from mommy_chaogu.tui.services.formatting import (
    change_arrow,
    change_color,
    format_change_pct,
    format_tokens_compact,
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


class TopBar(Static):
    """顶部状态栏：品牌 · 指数快照 · AI 状态 · 用量 · 时间。"""

    ai_label: reactive[str] = reactive("AI⚪ 未配置")

    def __init__(self) -> None:
        super().__init__()
        self._clock = ""
        self._index: dict[str, Any] | None = None
        self._theme = "dark"
        self._session_tokens = 0
        self._model = ""

    def on_mount(self) -> None:
        self.set_interval(1.0, self._tick)

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
        """喂入当前模型名（AI 已配置时显示在 AI 状态后）。"""
        self._model = model or ""
        self._refresh_display()

    def set_session_usage(self, total_tokens: int) -> None:
        """喂入本会话累计 token（app 在每轮结束后调用）。0 时不占位。"""
        self._session_tokens = max(0, int(total_tokens))
        self._refresh_display()

    def set_theme(self, theme: str) -> None:
        """主题切换后重渲染品牌色与涨跌颜色。"""
        self._theme = theme
        self._refresh_display()

    def _brand_text(self) -> str:
        accent = color(self._theme, "accent")
        muted = color(self._theme, "muted")
        return (
            f"[bold {accent}]◕‿◕[/] [bold]妈咪炒股[/][bold {accent}]↗[/]"
            f" [{muted}]AI 投研 Agent[/] [{color(self._theme, 'faint')}]│[/]"
        )

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

    def _refresh_display(self) -> None:
        ai = self.ai_label
        if self._model and "🟢" in ai:
            ai += f" [dim]{escape(self._model)}[/]"
        parts = [
            self._brand_text(),
            self._index_text(),
            f"[dim]·[/] {ai}",
        ]
        if self._session_tokens > 0:
            parts.append(f"[dim]· ∑ {format_tokens_compact(self._session_tokens)} tok[/]")
        parts.append(f"[dim]· {self._clock}[/]")
        self.update(" ".join(parts))

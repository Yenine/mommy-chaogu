"""妈咪状态机：跟随 Agent 活动切换姿势与台词（纯函数，无 UI）。

台词与姿势取自 Mommy Mascot 设计稿；终端里用颜文字代替 PNG 立绘。

    忙碌 + 刚失败（<2s）   → 咦？出错了
    忙碌 + 有工具在跑      → 按工具名选姿势（多个并行时 ×N）
    忙碌 + 无工具          → 让我想想…（规划下一步）
    刚完成（<4s）          → 赚到了！
    刚中断（<4s）          → 等等…
    空闲 >90s / >30s       → Zzz… / 先喝杯咖啡
    被点一下（<2.5s）      → 嗨～我是妈咪！+ 试用建议
"""

from __future__ import annotations

from dataclasses import dataclass

# 姿势 → 两行颜文字（上：表情，下：道具），宽度控制在 12 列内
FACES: dict[str, tuple[str, str]] = {
    "hero": ("(◕‿◕)ゞ", " ╰ 妈咪 ╯"),
    "research": ("(•̀ᴗ•́)", " ⌨ 研究中"),
    "up": ("(≧▽≦)↗", "  ▁▃▅▇"),
    "news": ("(◔_◔)", " ▤ 读报"),
    "deep": ("(ಠ‿ಠ)", " ⌕ 深挖"),
    "win": ("\\(^o^)/", "  ★ ★"),
    "wait": ("(￣ー￣)", "  …"),
    "coffee": ("(ˇ▽ˇ)", "  c[_]"),
    "think": ("(・_・ヾ", "  ?"),
    "huh": ("(⊙_⊙)?", "  !"),
    "sleep": ("(－_－)", "  zZ"),
}

LINES: dict[str, str] = {
    "hero": "嗨～我是妈咪！",
    "research": "研究中…",
    "up": "冲！",
    "news": "收到！",
    "deep": "好机会！",
    "win": "赚到了！",
    "wait": "等等…",
    "coffee": "先喝杯咖啡",
    "think": "让我想想…",
    "huh": "咦？出错了",
    "sleep": "Zzz…",
}

# 工具名 → 姿势（agent/tools 全部工具名；未列出的按「研究中」）
TOOL_POSES: dict[str, str] = {
    "search_news": "news",
    "get_announcements": "news",
    "get_longhuban": "news",
    "get_market_narrative": "news",
    "search_similar_events": "news",
    "get_quote": "up",
    "get_quotes": "up",
    "get_market_indexes": "up",
    "get_bars": "up",
    "get_index_bars": "up",
    "get_sector_bars": "up",
    "get_money_flow_today": "up",
    "get_money_flow_history": "up",
    "screen_inflow_stocks": "deep",
    "check_kline_signal": "deep",
    "check_earnings_catalyst": "deep",
    "get_sector_momentum": "deep",
    "get_sector_ranking": "deep",
    "market_regime_series": "deep",
    "detect_market_changes": "deep",
    "get_portfolio_analysis": "deep",
}

FAIL_HOLD_S = 2.0
EVENT_HOLD_S = 4.0
POKE_HOLD_S = 2.5
COFFEE_AFTER_S = 30.0
SLEEP_AFTER_S = 90.0


@dataclass(frozen=True)
class MascotState:
    pose: str
    line: str
    sub: str
    tone: str  # 状态点语义色：warning（忙）/ success / danger / muted


def mascot_state(
    *,
    busy: bool,
    running: list[str],
    running_for_s: float = 0.0,
    event: str | None = None,
    event_age_s: float = 1e9,
    idle_s: float = 0.0,
    poke_age_s: float = 1e9,
) -> MascotState:
    """根据当前活动算出妈咪的姿势、台词、副标题与状态点颜色。"""
    if busy:
        if event == "fail" and event_age_s < FAIL_HOLD_S:
            return MascotState("huh", LINES["huh"], "失败的步骤，妈咪在想办法", "danger")
        if running:
            pose = TOOL_POSES.get(running[-1], "research")
            line = LINES[pose] + (f" ×{len(running)}" if len(running) > 1 else "")
            sub = " · ".join(running) + f" · {_dur(running_for_s)}"
            return MascotState(pose, line, sub, "warning")
        return MascotState("think", LINES["think"], "规划下一步", "warning")
    if event == "win" and event_age_s < EVENT_HOLD_S:
        return MascotState("win", LINES["win"], "本轮完成 · 结果已输出", "success")
    if event == "stop" and event_age_s < EVENT_HOLD_S:
        return MascotState("wait", LINES["wait"], "已中断 · 等你下一步指令", "muted")
    if event == "fail" and event_age_s < EVENT_HOLD_S:
        return MascotState("huh", LINES["huh"], "本轮出错 · 换个说法试试", "danger")
    if poke_age_s < POKE_HOLD_S:
        return MascotState("hero", LINES["hero"], "试试 /today 或 @茅台", "success")
    if idle_s > SLEEP_AFTER_S:
        return MascotState("sleep", LINES["sleep"], "空闲中 · 输入任意内容叫醒我", "muted")
    if idle_s > COFFEE_AFTER_S:
        return MascotState("coffee", LINES["coffee"], "空闲中", "muted")
    return MascotState("hero", LINES["hero"], "就绪 · 输入 / 查看命令", "success")


def _dur(seconds: float) -> str:
    return f"{seconds * 1000:.0f}ms" if seconds < 1 else f"{seconds:.1f}s"

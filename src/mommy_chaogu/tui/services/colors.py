"""TUI 语义色板：chrome 颜色的单一真相源，随 ui_theme 切换。

与 CSS 的分工：``styles.tcss`` 用 Textual 主题 token（``$text-muted`` /
``$accent`` / ``$warning``，随当前 textual 主题自动切换）；本模块服务
Python 侧的 inline markup。**数据红绿（A股涨跌）不在这里**——走
``formatting.change_color``（含色盲映射）。

主题定稿见「妈咪炒股」TUI 设计稿：妈咪 Dark / 妈咪 Light 加 10 套经典
编辑器配色（Tokyo Night、Catppuccin、Dracula、Nord、Gruvbox、One Dark、
GitHub、Solarized、Rosé Pine）。每套主题由同一组设计 token 生成两样东西：

- ``_PALETTES[theme]``：Python 侧语义色（info / success / danger …）
- ``TEXTUAL_THEMES``：注册给 Textual 的 ``mommy-<theme>`` 主题（CSS token）

``colorblind`` 沿用妈咪 Dark 的 chrome 色——这里的色表达的是 UI 语义
（允许/拒绝/警告），不是涨跌数据；涨跌的色盲映射在 ``change_color``。
``github-dark`` 是旧版 ``github`` 主题的延续（设计稿之外保留，避免老用户
配置失效）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual.theme import Theme


@dataclass(frozen=True)
class _Tokens:
    """设计稿 CSS 变量（--bg / --bg2 / --text …）的子集。"""

    label: str
    dark: bool
    bg: str  # 主背景
    bg2: str  # 顶栏 / 右侧面板
    panel: str  # 用户消息底 / 思考块底
    text: str
    dim: str  # 次要文字
    faint: str  # 更淡的提示文字
    accent: str  # 主色：提示符 / 选中 / 完成
    accent_h: str  # 主色高亮（思考块）
    run: str  # 运行中
    fail: str  # 失败
    blue: str  # 信息 / 轮次编号
    track: str  # 时间线进度条底轨


_TOKENS: dict[str, _Tokens] = {
    "dark": _Tokens(
        "妈咪 Dark",
        True,
        "#0b0d10",
        "#0e1014",
        "#14171c",
        "#d6dae0",
        "#6b7380",
        "#4d5560",
        "#5fd7af",
        "#8ff0cc",
        "#e5b567",
        "#ef6b73",
        "#82aaff",
        "#171b21",
    ),
    "light": _Tokens(
        "妈咪 Light · 妈咪紫",
        False,
        "#f8f7fc",
        "#efecf8",
        "#ece8f8",
        "#1f2142",
        "#5f6283",
        "#777a9a",
        "#6a55c9",
        "#4f3ba8",
        "#b0700a",
        "#d1343f",
        "#1f8fb3",
        "#e6e2f3",
    ),
    "tokyo-night": _Tokens(
        "Tokyo Night",
        True,
        "#1a1b26",
        "#16161e",
        "#1f2335",
        "#c0caf5",
        "#7a82ab",
        "#565f89",
        "#7aa2f7",
        "#a9c1ff",
        "#e0af68",
        "#f7768e",
        "#7dcfff",
        "#24283b",
    ),
    "catppuccin-mocha": _Tokens(
        "Catppuccin Mocha",
        True,
        "#1e1e2e",
        "#181825",
        "#232334",
        "#cdd6f4",
        "#7f849c",
        "#6c7086",
        "#cba6f7",
        "#e0c8ff",
        "#f9e2af",
        "#f38ba8",
        "#89dceb",
        "#313244",
    ),
    "dracula": _Tokens(
        "Dracula",
        True,
        "#282a36",
        "#21222c",
        "#2e3040",
        "#f8f8f2",
        "#8590b8",
        "#6272a4",
        "#bd93f9",
        "#d6bcff",
        "#f1fa8c",
        "#ff5555",
        "#8be9fd",
        "#343746",
    ),
    "nord": _Tokens(
        "Nord",
        True,
        "#2e3440",
        "#292e39",
        "#333946",
        "#eceff4",
        "#8a94a8",
        "#6d778b",
        "#88c0d0",
        "#a9d6e2",
        "#ebcb8b",
        "#bf616a",
        "#81a1c1",
        "#3b4252",
    ),
    "gruvbox-dark": _Tokens(
        "Gruvbox Dark",
        True,
        "#282828",
        "#1d2021",
        "#32302f",
        "#ebdbb2",
        "#928374",
        "#7c6f64",
        "#b8bb26",
        "#d5d84a",
        "#fabd2f",
        "#fb4934",
        "#83a598",
        "#3c3836",
    ),
    "one-dark": _Tokens(
        "One Dark",
        True,
        "#282c34",
        "#21252b",
        "#2c313a",
        "#abb2bf",
        "#7f848e",
        "#5c6370",
        "#61afef",
        "#8cc6ff",
        "#e5c07b",
        "#e06c75",
        "#56b6c2",
        "#2c313a",
    ),
    "github-light": _Tokens(
        "GitHub Light",
        False,
        "#ffffff",
        "#f6f8fa",
        "#f6f8fa",
        "#1f2328",
        "#59636e",
        "#6e7781",
        "#0969da",
        "#0550ae",
        "#9a6700",
        "#cf222e",
        "#1a7f37",
        "#eaeef2",
    ),
    "solarized-light": _Tokens(
        "Solarized Light",
        False,
        "#fdf6e3",
        "#eee8d5",
        "#f1ebd7",
        "#3b4d55",
        "#657b83",
        "#7c8b8e",
        "#268bd2",
        "#1a6aa3",
        "#b58900",
        "#dc322f",
        "#2aa198",
        "#e9e2cc",
    ),
    "catppuccin-latte": _Tokens(
        "Catppuccin Latte",
        False,
        "#eff1f5",
        "#e6e9ef",
        "#e6e9ef",
        "#4c4f69",
        "#6c6f85",
        "#7c7f93",
        "#8839ef",
        "#6c22c9",
        "#df8e1d",
        "#d20f39",
        "#1e66f5",
        "#dce0e8",
    ),
    "rose-pine-dawn": _Tokens(
        "Rosé Pine Dawn",
        False,
        "#faf4ed",
        "#f2e9e1",
        "#f4ede8",
        "#464261",
        "#797593",
        "#8b87a3",
        "#907aa9",
        "#6f5a8c",
        "#c27a12",
        "#b4637a",
        "#286983",
        "#ece5df",
    ),
    "github-dark": _Tokens(
        "GitHub Dark",
        True,
        "#0d1117",
        "#161b22",
        "#21262d",
        "#e6edf3",
        "#8b949e",
        "#6e7681",
        "#58a6ff",
        "#bc8cff",
        "#d29922",
        "#f85149",
        "#3fb950",
        "#21262d",
    ),
}
_TOKENS["colorblind"] = _Tokens(**{**_TOKENS["dark"].__dict__, "label": "色盲友好（跌=蓝）"})

# 选择器 / Ctrl+T 循环顺序：设计稿 12 套在前，延续主题在后
THEMES = (
    "dark",
    "light",
    "colorblind",
    "tokyo-night",
    "catppuccin-mocha",
    "dracula",
    "nord",
    "gruvbox-dark",
    "one-dark",
    "github-dark",
    "github-light",
    "solarized-light",
    "catppuccin-latte",
    "rose-pine-dawn",
)

# 浅底主题：前景必须用深色变体（守卫测试据此校验）
LIGHT_BG_THEMES = tuple(t for t in THEMES if not _TOKENS[t].dark)

# 旧主题名 / 中文别名 → 现主题（MOMMY_TUI_THEME 与 /theme 共用）
THEME_ALIASES: dict[str, str] = {
    "solarized": "solarized-light",
    "latte": "catppuccin-latte",
    "atom": "one-dark",
    "tokyo": "tokyo-night",
    "github": "github-dark",
    "mocha": "catppuccin-mocha",
    "gruvbox": "gruvbox-dark",
    "rose-pine": "rose-pine-dawn",
    "日光": "solarized-light",
    "极夜": "nord",
    "拿铁": "catppuccin-latte",
    "浅色": "light",
    "深色": "dark",
}

THEME_LABELS: dict[str, str] = {t: _TOKENS[t].label for t in THEMES}

# 主题色板取不到时的中性兜底（选择器色板/未知主题）
FALLBACK_BG = "#888888"

ROLES = (
    "info",
    "success",
    "danger",
    "warning",
    "muted",
    "thinking",
    "accent",
    "faint",
    "track",
)


def _palette(tk: _Tokens) -> dict[str, str]:
    return {
        "info": tk.blue,  # 活动圈点 / 选中高亮 / 会话放行 / 轮次编号
        "success": tk.accent,  # 已允许 / 完成
        "danger": tk.fail,  # 错误 / 已拒绝 / 失败
        "warning": tk.run,  # 确认条 / 重试 / 运行中
        "muted": tk.dim,  # 次要信息 / 摘要 / 回执
        "thinking": tk.accent_h,  # 思考块
        "accent": tk.accent,  # 品牌主色（提示符 / 菜单选中）
        "faint": tk.faint,  # 最淡提示（快捷键说明）
        "track": tk.track,  # 时间线进度条底轨
    }


_PALETTES: dict[str, dict[str, str]] = {name: _palette(tk) for name, tk in _TOKENS.items()}


def textual_theme_name(theme: str) -> str:
    """ui_theme → 注册给 Textual 的主题名（colorblind 共用妈咪 Dark）。"""
    key = "dark" if theme == "colorblind" else theme
    return f"mommy-{key}" if key in _TOKENS else "mommy-dark"


TEXTUAL_THEMES: tuple[Theme, ...] = tuple(
    Theme(
        name=textual_theme_name(name),
        primary=tk.accent,
        secondary=tk.blue,
        accent=tk.accent,
        warning=tk.run,
        error=tk.fail,
        success=tk.accent,
        foreground=tk.text,
        background=tk.bg,
        surface=tk.bg2,
        panel=tk.panel,
        dark=tk.dark,
    )
    for name, tk in _TOKENS.items()
    if name != "colorblind"
)


def theme_background(theme: str) -> str:
    """主题代表背景色（选择器色板用）。"""
    tk = _TOKENS.get(theme)
    return tk.bg if tk is not None else FALLBACK_BG


def resolve_theme(name: str) -> str | None:
    """主题名 / 旧名 / 中文别名 → 现主题名；未知返回 None。"""
    key = name.strip()
    key = THEME_ALIASES.get(key, THEME_ALIASES.get(key.lower(), key.lower()))
    return key if key in THEMES else None


def current_theme() -> str:
    """当前 App 的 ui_theme；无 App 上下文（纯函数/测试）回退 dark。"""
    try:
        # active_app 是公开 ContextVar 但不在 textual.app 的显式导出里，
        # strict mypy 需要定点 ignore（同 chat.py 对 action_cycle_theme 的处理）。
        from textual.app import active_app  # type: ignore[attr-defined]

        app: Any = active_app.get()
        return str(getattr(app, "ui_theme", "dark"))
    except Exception:
        return "dark"


def color(theme: str, role: str) -> str:
    """按主题取语义色。未知主题回退 dark，未知角色直接 KeyError。"""
    return _PALETTES.get(theme, _PALETTES["dark"])[role]

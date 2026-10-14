"""终端图片支持：妈咪立绘 / Logo 在支持图片协议的终端里显示真图。

检测必须在 Textual 接管终端**之前**完成（``textual_image.renderable`` 导入时会向
终端发查询序列并读回应），所以 ``main()`` 启动前调用一次 :func:`detect`；App
内部只读结果，绝不在运行中触发检测。

只有 Kitty 图形协议（Kitty / WezTerm / Ghostty / iTerm2 新版）或 Sixel 才用真图；
半格块 / Unicode 回退在这个尺寸下只是一团色块，不如颜文字，继续用颜文字。
``MOMMY_TUI_IMAGES=off`` 可强制关闭。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

_log = logging.getLogger(__name__)

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "mascot"

# 妈咪姿势 → 立绘文件（取自 Mommy Mascot 设计稿）
POSE_IMAGES: dict[str, str] = {
    "hero": "hero.png",
    "research": "p_research.png",
    "up": "p_up.png",
    "news": "p_news.png",
    "deep": "p_deep.png",
    "win": "p_win.png",
    "wait": "p_wait.png",
    "coffee": "p_coffee.png",
    "think": "e_think.png",
    "huh": "e_huh.png",
    "sleep": "e_sleep.png",
}
LOGO_IMAGE = "logo_face.png"

_supported: bool = False


def detect() -> bool:
    """探测终端是否支持图片协议（仅在 App 启动前调用）。"""
    global _supported
    if os.environ.get("MOMMY_TUI_IMAGES", "").strip().lower() in ("off", "0", "false", "no"):
        _supported = False
        return _supported
    try:
        from textual_image import renderable

        _supported = renderable.Image in (renderable.TGPImage, renderable.SixelImage)
    except Exception as e:  # 依赖缺失 / 终端查询异常：退回颜文字，不影响启动
        _log.debug("终端图片协议检测失败: %s", e)
        _supported = False
    return _supported


def supported() -> bool:
    """detect() 的结果；未调用过（如测试）恒为 False。"""
    return _supported


def asset(name: str) -> Path:
    return ASSETS / name

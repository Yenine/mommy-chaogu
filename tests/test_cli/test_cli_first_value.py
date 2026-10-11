"""P-1 CLI 无 Key 首个价值时刻：渲染层与日志收敛测试。"""

from __future__ import annotations

import logging
from typing import Any

from mommy_chaogu.cli import _configure_cli_logging
from mommy_chaogu.cli_repl import print_workflow_result
from mommy_chaogu.workflow.engine import StepResult, WorkflowResult


def _result(*steps: StepResult) -> WorkflowResult:
    return WorkflowResult(workflow_id="w", steps=list(steps))


def _step(data: Any, *, display: str = "步骤") -> StepResult:
    return StepResult(display_name=display, tool_name="t", success=True, data=data)


# ---------- 范围 1：dict 值级渲染 ----------


def test_single_quote_dict_renders_values_not_field_names(capsys: Any) -> None:
    sr = _step(
        {
            "code": "600519",
            "name": "贵州茅台",
            "price": 1272.08,
            "change_pct": 1.32,
            "open": 1255.42,
            "volume": 26000,
        }
    )
    print_workflow_result(_result(sr))
    out = capsys.readouterr().out
    assert "600519" in out and "贵州茅台" in out
    assert "1272.08" in out  # 值，而不是只出现 price 字段名
    assert "1.32" in out
    assert "open: 1255.42" in out


def test_unknown_dict_renders_scalar_values_lists_folded(capsys: Any) -> None:
    sr = _step({"foo": "bar", "n": 3, "flag": True, "items": [1, 2], "nested": {"a": 1}})
    print_workflow_result(_result(sr))
    out = capsys.readouterr().out
    assert "foo: bar" in out
    assert "n: 3" in out
    assert "flag: 是" in out
    assert "items" not in out  # 列表折叠，不回显
    assert "nested" not in out  # 嵌套 dict 折叠


def test_existing_indexes_render_unchanged(capsys: Any) -> None:
    sr = _step({"indexes": [{"name": "上证指数", "price": 3200.5, "change_pct": 0.5}]})
    print_workflow_result(_result(sr))
    out = capsys.readouterr().out
    assert "上证指数" in out and "3200.5" in out


# ---------- 范围 2：空数据 / error 的显式中文原因 ----------


def test_empty_list_step_shows_chinese_reason(capsys: Any) -> None:
    sr = _step([])
    print_workflow_result(_result(sr))
    out = capsys.readouterr().out
    assert "共 0 条" not in out
    assert "东财源不可达或该代码无数据" in out


def test_error_dict_step_surfaces_message(capsys: Any) -> None:
    sr = _step({"error": "未找到股票 600519 的行情", "hint": "可用 search_stock 按名称搜索代码"})
    print_workflow_result(_result(sr))
    out = capsys.readouterr().out
    assert "未找到股票 600519 的行情" in out
    assert "search_stock" in out


def test_empty_known_key_shows_reason(capsys: Any) -> None:
    sr = _step({"indexes": []})
    print_workflow_result(_result(sr))
    out = capsys.readouterr().out
    assert "数据源不可达或该范围暂无数据" in out


# ---------- 范围 4：非 -v 收敛英文告警，-v 保留 ----------


def test_non_verbose_suppresses_package_and_upstream_warnings() -> None:
    names = ["mommy_chaogu", "efinance", "urllib3", "requests"]
    saved = {name: logging.getLogger(name).level for name in names}
    try:
        for name in names:
            logging.getLogger(name).setLevel(logging.NOTSET)
        _configure_cli_logging(False)
        for name in names:
            assert logging.getLogger(name).isEnabledFor(logging.WARNING) is False
    finally:
        for name, level in saved.items():
            logging.getLogger(name).setLevel(level)


def test_verbose_keeps_warnings_visible() -> None:
    name = "mommy_chaogu"
    saved = logging.getLogger(name).level
    try:
        logging.getLogger(name).setLevel(logging.WARNING)
        _configure_cli_logging(True)
        assert logging.getLogger(name).isEnabledFor(logging.WARNING) is True
    finally:
        logging.getLogger(name).setLevel(saved)

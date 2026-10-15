"""跨层数据来源词汇一致性（P8）。

``cache/adapter.SOURCE_VALUES`` 是 ``last_source`` 词汇表的单一真相源；
本文件从该常量参数化，钉死三个消费方的一致性：

1. TUI bars 卡的旧缓存警示集合 ⊆ 词汇表（指向永不出现的值 = 警示静默失效）；
2. ``format_source_label_from`` 对每个词汇值都有人话映射——漏映射时 else
   分支会把英文 token 裸显给用户，此漏洞在此收敛为断言；
3. verify_engine 透传 adapter 标注的来源，不得把 cache/stale_cache 谎标为
   ``"adapter"``（裸链才回退 adapter）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.agent.verify_engine import verify_one
from mommy_chaogu.cache.adapter import SOURCE_VALUES, CachedMarketDataAdapter
from mommy_chaogu.tui.widgets import cards


def _label_adapter() -> CachedMarketDataAdapter:
    """不触网的缓存装饰器：只渲染标签，inner 用 MagicMock。

    MagicMock 的类名不含 Efinance/Tencent，network/snapshot 的映射落到
    「实时数据」——对断言「不裸显英文 token」而言足够确定。
    """
    return CachedMarketDataAdapter(MagicMock(), MagicMock())


def _pending_pred() -> dict[str, object]:
    """构造一条已到验证期的方向预测（verify_one 可判终态）。"""
    return {
        "id": 1,
        "code": "603662",
        "name": "柯力传感",
        "prediction": "底部反转",
        "direction": "bullish",
        "target_price": None,
        "entry_price": 80.0,
        "timeframe": "5d",
        "created_at": (datetime.now(UTC) - timedelta(days=6)).isoformat(),
        "verify_attempts": 0,
    }


def _quote_mock() -> MagicMock:
    q = MagicMock()
    q.price = 83.0
    q.change_pct = 3.75
    return q


class TestStaleWarningSubset:
    def test_tui_stale_warning_set_is_subset_of_source_values(self) -> None:
        """bars 卡警示集合必须落在 adapter 词汇表内。"""
        assert set(SOURCE_VALUES) >= cards.STALE_SOURCE_VALUES


class TestSourceLabelMapping:
    @pytest.mark.parametrize("source", SOURCE_VALUES)
    def test_every_vocabulary_value_has_user_facing_label(self, source: str) -> None:
        adapter = _label_adapter()
        label = adapter.format_source_label_from(source, trade_date="")
        if not source:
            assert label == ""
            return
        assert label, f"{source}: 标签为空"
        assert label != source, f"{source}: 英文 token 裸显给用户（缺人话映射）"


class TestVerifyEnginePassthrough:
    @pytest.mark.parametrize("source", [v for v in SOURCE_VALUES if v], ids=lambda v: v or "empty")
    def test_verify_one_passes_adapter_source_through(self, source: str) -> None:
        """adapter 标注的来源原样透传进验证记录（cache/stale_cache ≠ adapter）。"""
        adapter = MagicMock()
        adapter.get_quote.return_value = _quote_mock()
        adapter.last_source = source

        result = verify_one(_pending_pred(), adapter)

        assert result.quote_source == source
        assert result.quote_source != "adapter"

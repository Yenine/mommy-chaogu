"""交易级简化收益汇总：把一组已验证的预测按交易记录顺序汇总。

之前的 :mod:`backtest.engine` / :mod:`backtest.scoring` 只看「单条预测准不准」，
本模块提供便于筛查的交易级收益观察，不等同逐日持仓组合回测。

交易规则（A 股约束）:

- **bullish** → 等额资金开多，持有到期平仓，计算净收益
- **bearish** → A 股不能做空，按「空仓回避」处理，不产生交易
- **neutral** → 方向不明，不产生交易

资金分配（``position_size``）:

- ``"equal"``: 每个实际开仓信号分到 ``initial_capital / 实际交易笔数`` 的
  等额资金。**注意**：总笔数在回看全样本后才知道，属于前视；返回值
  ``caveats`` 会显式标注。
- ``"sequential"``: 按日期顺序把每笔收益按**当时汇总净值**的固定比例
  ``sequential_fraction``（默认 10%）计入；仍未模拟逐日持仓与退出日期。

资金金额（initial_capital / equity / P&L）全程 :class:`~decimal.Decimal`，
输出时 quantize 到分。观察曲线按信号 ``date`` 排序后顺序累加每笔 P&L；
它不代表逐日组合净值，最大回撤和夏普比率也不具备严格组合指标含义。
交易成本走 :func:`backtest.costs.apply_costs`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from mommy_chaogu.backtest.costs import apply_costs
from mommy_chaogu.backtest.metrics import drawdown_fraction, sharpe_ratio
from mommy_chaogu.backtest.scoring import score_direction

__all__ = [
    "EQUAL_LOOKAHEAD_CAVEAT",
    "EXECUTION_TIMING_CAVEAT",
    "SIMPLIFIED_SUMMARY_CAVEAT",
    "PortfolioBacktester",
    "PortfolioResult",
]

_TWO_PLACES = Decimal("0.01")

EQUAL_LOOKAHEAD_CAVEAT = (
    "equal 等权分配按全样本交易笔数切分初始资金（前视）：按日期滚动执行时"
    "无法预知总笔数，需把该资金分配限制纳入解释。"
)

SIMPLIFIED_SUMMARY_CAVEAT = (
    "交易级简化收益汇总：未按逐日持仓锁定资金，未模拟 exit_date 重叠、资金占用"
    "或可复用现金；equity、最大回撤和夏普仅为观察值，不是严格组合指标"
)

EXECUTION_TIMING_CAVEAT = "未验证信号产生、可见时间、成交与到期平仓时点，结果不代表可执行收益"


def _q2(value: Decimal) -> float:
    """Decimal → 保留两位小数的 float（净值曲线 / API 输出用）。"""
    return float(value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP))


@dataclass
class PortfolioResult:
    """交易级简化收益汇总结果。

    Attributes:
        caveats: 口径警示（如 equal 分配的前视标注），调用方应展示给用户。
    """

    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    win_rate: float
    num_trades: int
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


class PortfolioBacktester:
    """对预测记录生成交易级收益、胜率和观察性净值序列。"""

    def __init__(self, default_horizon: int = 5) -> None:
        """单笔交易的默认持有天数，仅用于夏普年化系数。

        Args:
            default_horizon: 默认持有天数（默认 5，与 ``scripts/backtest_llm.py`` 对齐）
        """
        self.default_horizon = default_horizon

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------

    def simulate(
        self,
        predictions: list[dict[str, Any]],
        initial_capital: Decimal | float | int = Decimal("1000000"),
        position_size: str = "equal",
        sequential_fraction: float = 0.1,
    ) -> PortfolioResult:
        """对一组已验证的预测模拟组合操作。

        Args:
            predictions: 预测字典列表。每条至少需能推出方向和到期涨跌幅：

                - ``direction``: ``"bullish"`` / ``"bearish"`` / ``"neutral"``
                - 到期涨跌幅（任一）: ``change_pct``（%，已算好），
                  或 ``entry`` + ``actual`` / ``exit_price``（价格）
                - ``date``: 开仓日期（可选，用于净值曲线排序）
            initial_capital: 初始资金（元）；接受 Decimal / float / int，
                内部统一转 Decimal 精确累加
            position_size: 资金分配策略——``"equal"``（等权，含前视，见模块
                docstring）或 ``"sequential"``（按汇总净值固定比例）
            sequential_fraction: ``"sequential"`` 模式下每笔投入当时净值的
                比例（默认 0.1）

        Returns:
            :class:`PortfolioResult`
        """
        if position_size not in ("equal", "sequential"):
            raise ValueError(
                f"不支持的 position_size: {position_size!r}（支持 'equal' / 'sequential'）"
            )

        capital = Decimal(str(initial_capital))
        caveats: list[str] = [SIMPLIFIED_SUMMARY_CAVEAT, EXECUTION_TIMING_CAVEAT]
        if position_size == "equal":
            caveats.append(EQUAL_LOOKAHEAD_CAVEAT)

        # 空输入边界：净值曲线只含初始点
        if not predictions:
            return PortfolioResult(
                total_return_pct=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                win_rate=0.0,
                num_trades=0,
                equity_curve=[{"date": "", "equity": _q2(capital)}],
                caveats=caveats,
            )

        # 1. 只对 bullish 开多；bearish / neutral = 空仓回避
        trades = self._build_trades(predictions)

        # 没有可平仓的信号 → 全程空仓
        if not trades:
            return PortfolioResult(
                total_return_pct=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                win_rate=0.0,
                num_trades=0,
                equity_curve=[{"date": "", "equity": _q2(capital)}],
                caveats=caveats,
            )

        # 2. 按日期排序，顺序累加 P&L 构建净值曲线
        trades.sort(key=lambda t: t["date"])
        equal_alloc = capital / Decimal(len(trades))
        equity = capital
        equity_curve: list[dict[str, Any]] = [{"date": "", "equity": _q2(equity)}]
        net_returns: list[float] = []
        for t in trades:
            if position_size == "equal":
                allocated = equal_alloc
            else:
                # sequential：每笔按当前汇总净值的固定比例计入观察值。
                allocated = equity * Decimal(str(sequential_fraction))
            pnl = allocated * Decimal(str(t["net_return_pct"])) / Decimal("100")
            equity += pnl
            equity_curve.append({"date": t["date"], "equity": _q2(equity)})
            net_returns.append(t["net_return_pct"])

        # 3. 组合统计
        total_return_pct = float((equity - capital) / capital * Decimal("100"))
        max_dd = drawdown_fraction([p["equity"] for p in equity_curve]) * 100
        sharpe = sharpe_ratio(net_returns, self.default_horizon)
        wins = sum(1 for r in net_returns if r > 0)
        win_rate = wins / len(net_returns) if net_returns else 0.0

        return PortfolioResult(
            total_return_pct=round(total_return_pct, 4),
            max_drawdown_pct=round(max_dd, 4),
            sharpe_ratio=round(sharpe, 4),
            win_rate=round(win_rate, 4),
            num_trades=len(trades),
            equity_curve=equity_curve,
            caveats=caveats,
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    @staticmethod
    def _build_trades(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """从预测列表提取实际开仓的交易记录。

        跳过：

        - 非 bullish 方向（bearish / neutral = 空仓回避）
        - 无法推出到期涨跌幅的预测（无 ``change_pct`` 且无 ``entry``/``actual``）

        每条交易记录::

            {"date": str, "gross_return_pct": float,
             "net_return_pct": float, "status": "hit"|"missed"}
        """
        trades: list[dict[str, Any]] = []
        for pred in predictions:
            direction = str(pred.get("direction", "")).strip().lower()
            if direction != "bullish":
                continue

            change_pct = _extract_change_pct(pred)
            if change_pct is None:
                continue

            net = apply_costs(change_pct, "bullish")
            # 用 score_direction 判定方向命中（与单条评分口径一致）
            status, _score = score_direction(direction, change_pct)
            trades.append(
                {
                    "date": str(pred.get("date", "")),
                    "gross_return_pct": change_pct,
                    "net_return_pct": net,
                    "status": status,
                }
            )
        return trades


# ----------------------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------------------


def _extract_change_pct(pred: dict[str, Any]) -> float | None:
    """从预测字典提取到期涨跌幅（%）。

    优先 ``change_pct``；否则用 ``entry`` 和 ``actual`` / ``exit_price`` 反推。
    """
    raw = pred.get("change_pct")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    entry = pred.get("entry")
    exit_price = pred.get("actual")
    if exit_price is None:
        exit_price = pred.get("exit_price")
    if entry and exit_price is not None and entry > 0:
        return (float(exit_price) - float(entry)) / float(entry) * 100
    return None

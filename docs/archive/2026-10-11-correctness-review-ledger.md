# v1.6.0 正确性审查与执行 ledger

## 基准、授权与用户结果

- 日期：2026-10-11（America/Los_Angeles）。基准版本 v1.6.0，branch `main`。
- 起始 HEAD：`0dca5d9353ec980ef8565fa9abdb7776f8346e17`。
- 既有改动：`AGENTS.md`、`docs/README.md`、未跟踪的 `docs/SYSTEMATIC-REVIEW-GUIDE.md`；保留。
- 用户授权：核实审查建议、落计划、GPT 5.6 Luna Max sub-agent 执行、主管独立验收；不使用 Linear。
- 执行 agent：`/root/correctness_executor`，model `gpt-5.6-luna`，effort `max`，共享工作区。
- 不提交、不推送、不发版、不改写用户数据库；测试使用临时数据。
- 完成事件：A 股信号不使用当日未完成日 K；板块日期和比较窗口可解释；数据口径及降级可见；
  简化交易汇总不宣称严格组合回测；安装解析失败不悄悄切换 main。
- 本轮为有边界的证据审查与修复，不是全系统已通过审计或策略有效性认证。

## 已检查调用链与证据边界

1. efinance 日 K（北京午夜转换为 UTC）→ cache → sector_momentum → Agent sector 工具。
2. adapter 日 K → Agent analysis `_completed_daily_bars` → check_kline_signal。
3. fallback 分钟 K → cache 请求复权与 none 并集 → Agent bars / Web BarOut / IntradayService。
4. PortfolioBacktester 公共导出 → 交易汇总与指标。源码搜索未发现产品入口直接调用该类；
   其公共 Python 接口和文档仍可能误导，不能宣称已证明 UI 影响。
5. install.sh → latest release API → uv tool install；CI 已有正式安装、资源、迁移与 Docker 检查。

证据是当前代码、现有测试检查和本机离线反例。没有核验实时供应商、GitHub release、真实升级、
完整 A/美股假期日历、全量研究工具、财报 PIT、并发状态或用户已有报告。

## 发现与处理决定

| ID / 优先级 | 状态与证据 | 决定与最小方案 | 测试缺口、兼容与用户验收 |
|---|---|---|---|
| T1 / P1 | 已证实：`analysis._completed_daily_bars` 使用机器 now 与 timestamp.date；2026-07-02 北京 10:00，日 K 为 07-01T16:00Z，函数仍返回此根 | 按北京时间判定日 K，统一处理 aware 与历史 naive；剔除未来日及当日收盘缓冲前的输入。只承诺 A 股当前工具，不引入完整交易所日历 | 现有 timestamp 测试只证明 aware UTC；增加 UTC/上海/纽约等价输入及 15:05 边界。无数据库变更；信号输入改变是正确性修复 |
| T2 / P1 | 已证实：`sector_momentum._row_from_bars` 直接 UTC.date；上例 as_of 为 07-01，实际市场日 07-02 | 在 A 股服务按北京日解释，排序与去重；不要迁移缓存键 | 当前 sector 测试用 naive 日期；加入生产 aware 午夜标签。排名和截止日显示正确 |
| Q1 / P1 | 条件性风险由代码确认：各板块 independently 尾取 N+1，直接排序；data_cutoff=max；上一窗口只对子集排名，却与全集 current rank 相减 | 离线构造不同末日/缺日/历史不足证明后修。采用明确一致日期向量的比较队列，排除不能满足者并列原因；rank_change 在相同样本池上比较，无法比较则 None。移除“排名上升=资金流入”暗示 | 现有测试主要验证等长同日期数学，另允许当前有排名但无 previous。新增不同时点、内部缺日、previous 子集；字段尽量增补、保留既有 ranking |
| D1 / P1 | 已证实契约缺口：cache.get_bars 首拉异常/None 返回空且 last_source=cache；增量失败返回旧条目后仍 cache；Agent bars 与 Web BarOut 丢弃 adjustment/currency | 局部修复 bars 来源状态与失败保旧；不要把所有空 list 宣称为已确认无数据（底层失败可能也返回空）。补充每根实际 adjustment/currency；混合口径的派生指标应拒绝或降级，禁止静默混算 | 现有 last_source failure 测试主要针对 quote。新增 bars 异常/None/空/节流/保旧、工具与 Web 元数据、Intraday 混合口径。维持 list 与 HTTP 主契约；全链路 typed result/concurrency 未解决须披露 |
| Q2 / P1 | 已证实：sequential 忽略 exit_date，07-01 至 07-10 的 +10% 到期收益已在 07-01 入账，再分配 07-02；结果 caveats=[] | 采用原建议允许的替代方案：保留计算与公共类兼容，准确命名为交易级简化收益汇总；所有模式警示无逐日资金占用/净值模拟、回撤和夏普限制，删除“sequential 无前视”及“equal 必然偏乐观”断言。不建设缺少数据支撑的真实组合引擎 | 测试目前断言 sequential 无 caveat，属于错误契约；保留数学测试，改为断言限制可见。公共收益数值不改；真实执行建模另立项 |
| R1 / P2 | 已证实：install.sh API 无法解析 tag 时退回 main；显式 source 也先解析默认来源 | 默认解析失败明确退出并提示显式 source，显式 source 跳过 latest 请求。用 mocked curl/uv 验证故障、有效 tag、空/无效响应与指定 source | 当前 installer smoke 是 fake uv，但 latest 请求仍可发网络；增加全离线契约测试。默认故障行为改变须 CHANGELOG；无需改变已发布包或用户配置 |

离线反例已运行：`PYTHONPATH=src .venv/bin/python` 调用以上公共/服务函数。
T1 输出 `intraday incomplete daily bar retained: 1`；T2 输出 expected 2026-07-02 / actual 2026-07-01。
Q2 输出开仓日净值 1009697.0、下一日 1019488.03，且 `caveats=[]`（本金 1000000，两笔 10%，fraction=.1）。
执行者须把反例转为持久化根因测试；主管用不同反例独立复核。

## 不按原建议全面建设的项

| 建议 | 本轮决定 | 重新考虑条件 |
|---|---|---|
| 统一 Market Calendar / Clock 大框架、港股扩展 | 延后；先修已确认 A 股路径。UTC 统一不等于日历完成 | 实际闭环需要假期/多市场会话规则，且现有组件无法复用 |
| 全面替换 adapter 返回类型与数据库元数据迁移 | 延后；局部状态修复不宣称完整 quality contract | 完成所有调用方盘点、并发证据、版本兼容与用户展示方案 |
| 改写旧缓存日期、复权键或全库回填 | 不执行；现有缺陷不证明所有旧数据错误 | 有范围证据、可恢复迁移及临时副本验证 |
| 财报和复权历史 PIT 仓库 | 延后；历史可用性无法从今日抓取补字段推导 | 有供应商历史版本/快照及明确研究目标 |
| 真正逐日组合回测、全套统计验证等级 | 延后；先准确披露现有计算限制 | 明确入场/退场、逐日价、标的池、交易规则和样本/基线 |
| 重建 CI、发布平台、大型结果数据平台 | 不建；已有 migration/installed resources/dist/Docker 检查可复用 | 真实缺口需要新检查；重要报告可先附输入/版本/参数 |
| 所有 date.today 与金额类型机械替换 | 不执行；搜索命中是线索，需逐入口核实 | 非本轮路径存在可复现结果变化后追加阶段 |

## MVP：执行顺序与验收矩阵

1. M1（T1、T2、Q1）：时间与截面比较。输出正确北京交易日；不同窗口不混排，排名变化不混用样本池。
2. M2（D1）：bars 数据降级和口径传播。失败保旧有标记；Agent/Web 保留复权与币种；混合口径指标不静默计算。
3. M3（Q2）：研究诚实命名。调用者看到简化汇总限制；旧数值可复核，sequential 不再被标为无前视。
4. M4（R1）：安装一致性。mock 故障不调用 uv install；显式 source 无需访问 latest；有效 tag 原样绑定。
5. M5：合并 CHANGELOG 用户可感知修复、更新必要文档，运行相关测试、ruff format/check、mypy strict、离线回归。
   记录准确命令/结果，未运行项明确说明；主管独立审 diff、反例与 ledger 后给出 PASS 或返修。

每个里程碑小范围修改，不另造通用平台。执行中若原触发条件不成立，记录反证并不实施该项。
新增问题写入 ledger，重大范围改变先回报；不擅自加入迁移或真实回测。

## Extensions

- 日历、typed quality result、PIT 数据和真实组合模拟：当前输入与兼容证据不足，按上表条件重启。**You can ignore this for now.**

## 执行记录（追加，不覆盖历史）

### Round 0：审查与派发

- 主管已读新指南与 execution-review-loop；执行者已只读规范。
- 基线测试正在运行：`.venv/bin/python -m pytest tests/test_services/test_sector_momentum.py tests/test_backtest_portfolio.py tests/test_install_script.py tests/test_market_data/test_timestamp_semantics.py -q -m 'not network'`。
- 主管反例结果如上。当前无实现修改，未验收。
- 后续执行者逐里程碑追加：时间、改动文件、证据命令及实际结果、偏离/未解决项、工作区状态。
- 最终主管记录独立验收结果；不存在提交时以 diff 与测试文件记录接受的改动，不伪造 commit。

### Round 1：M1–M5 执行记录（2026-10-11）

#### M1：Market Time、窗口与比较样本

- **T1 已修复**：`agent/tools/analysis.py` 将 aware 日 K 统一转为北京时间，保留
  历史 naive 的墙上时间；收盘缓冲前剔除当日根，未来日期不进入信号。新增 UTC、
  Asia/Shanghai、America/New_York 等价时刻矩阵测试以及 15:05 边界测试。
- **T2 已修复**：`services/sector_momentum.py` 按北京交易日归并、排序、去重；使用所有
  有效日期 union 的尾部作为显式参考向量，要求板块具备完整当前向量，旧末日/内部缺日
  板块列出 `missing_reference_dates` 排除原因，不再让交集悄悄拉长其他板块窗口。上一
  窗口只有在日期和样本均可比时计算排名变化，否则保留 `None` 并说明原因。
- **T3 已修复**：`backtest/engine.py` 的 A 股日 K 键使用 aware timestamp 的北京日期；
  反例含 `2026-07-01T16:00:00Z→close=100`、`2026-07-02T16:00:00Z→close=200`，
  `2026-07-02` 资金流只能匹配 close=100。保留 date-only/naive 兼容，不改写旧缓存。
- 新增 `market_data/time_utils.py` 仅做代码形式到市场日期的时区转换（六位数字、带
  sh/sz/bj 前缀和 BK 数字板块按上海；纯字母、`^` 指数按纽约）；`SHW`/`BK` 反例确认
  不被误判为上海。Agent bars、Web mapper、TUI bars_card 共用该 helper。

#### M2：Data Quality、降级与用户可见口径

- **D1 已修复（局部契约）**：`CachedMarketDataAdapter` 为每个 K 线请求 key 保留来源
  状态，交错 code/口径/方法不会沿用另一个请求的 `last_source`；失败后旧缓存持续标记
  `stale_cache`，无缓存的异常/`None`/空列表标为不可用而不写“确认空数据”。Agent 每根
  K 线保留 `trade_date`、实际 `adjustment`、`currency`、`data_source`；Web 保留
  `trade_date`、`adjustment`、`currency`；日内混合复权或币种拒绝混算；Web K 线混合口径
  返回 503；TUI bars_card 显示 stale 和混合口径 warning。Web stale 来源展示仍未解决，
  并发状态与完整 typed-result 契约仍未验收。
- **D2 已修复（Web API 局部范围）**：`web/routes/quotes.py` 当日/历史资金流上游抛错或
  返回空列表时返回 503，不再生成五项累计 `0`；包含真实零值记录的非空结果仍保持成功
  响应。资金流前端页面和所有 downstream UI 的展示链路未宣称已完成验收。

#### M3：Quantitative Validation 与诚实命名

- **Q2 已修复**：`backtest/portfolio.py` 和 `backtest/engine.py` 的结果命名/说明改为
  “交易级简化收益汇总”或“探索性信号收益观察”。所有模式说明未模拟逐日持仓、现金
  复用、退出重叠和可执行成交时点；移除 sequential “无前视”和 equal “结果偏乐观”的
  无条件方向性断言，保留 equal 全样本计数前视限制与原数学结果兼容。
- `analysis` 与 workflow summary 不再把“复权未核验”解释成默认“未复权”，改为沿用返回
  K 线的实际口径并标注可比性限制。
- 未验证同收盘资金流是否可成交、逐日组合净值、真实执行回测、样本 PIT 和完整收益统计；
  本轮没有引入组合引擎或日历框架。

#### M4：Release Integrity

- **R1 已修复**：`install.sh` 显式 `MOMMY_INSTALL_SOURCE` 完全跳过 latest API；默认
  latest 无法解析或 curl 非零时失败，不静默回退 `main`；有效 `v1.2.3` 的 archive
  tag 原样传给 uv。新增 fake curl/uv 全离线测试覆盖显式 source、有效 tag、空响应和
  curl 非零。
- 未运行真实网络安装、GitHub release API、tag tarball、升级回滚或 CI release gate；
  这些不是本轮离线证据可以替代的检查。

#### M5：交付与验证记录

- `CHANGELOG.md` `[Unreleased]` 已记录时间窗口、数据质量、探索性结果边界、资金流 503
  和安装来源行为；本 ledger 追加本轮证据。保留既有 `AGENTS.md`、`docs/README.md`、
  `docs/SYSTEMATIC-REVIEW-GUIDE.md` 改动。
- 主管独立离线回归：
  `.venv/bin/python -m pytest -m 'not network' -o addopts='' -q` → **2550 passed,
  14 deselected，3 warnings**（FastAPI/Starlette 与 httpx 弃用提示）。
- 执行者新增边界目标集：
  `.venv/bin/python -m pytest -o addopts='' -q tests/test_tools/test_analysis.py
  tests/test_services/test_sector_momentum.py tests/test_install_script.py
  tests/test_workflow/test_definitions.py` → **103 passed**。
- 安装器在新增“响应体虽有 tag 但 curl 非零”反例后重新执行
  `.venv/bin/python -m pytest -o addopts='' -q tests/test_install_script.py` → **6 passed**；
  `sh -n install.sh` → 通过。
- `.venv/bin/ruff format --check .` → **451 files already formatted**；
  `.venv/bin/ruff check .` → **All checks passed**；
  `.venv/bin/mypy --strict src` → **Success: no issues found in 226 source files**；
  `git diff --check` → 通过。
- 当前工作区仍未提交、未推送、未迁移、未修改用户数据库或启动后台服务；测试产生的
  已知 `x.db` 保持可见，未用 gitignore 掩盖。最终 Git 状态由主管独立复核。

#### 仍属范围外的能力

- 完整交易所日历、供应商发布延迟/当期日 K 未完成状态、多市场会话、全量并发来源隔离、
  Web 图表单一降级口径展示、资金流 UI downstream、研究工具全链路、财报 PIT、真实逐日
  组合回测和网络发布安装仍未验证。
- 未建设通用 Market Calendar、typed result 大改、数据库 schema/历史缓存迁移或真实组合
  引擎；这些需要新的用户目标、数据证据、恢复方案和独立授权。

### Round 2：主管独立验收（2026-10-11，PASS：本轮限定范围）

- 执行者为用户指定的 GPT 5.6 Luna Max；主管未接管生产实现。修复过程审阅并返回了
  日期交集拉长窗口、来源跨请求污染、美股 SHW/BK 误判及文档 Web 来源字段夸大等问题，
  最终代码或记录已纠正。没有把执行者的自报 PASS 当作验收依据。
- 最终重新检查生产 diff、共享日期 helper、安装 shell、CHANGELOG 与 ledger；
  既有三份规范文档保留。HEAD 仍为起始 `0dca5d9353ec980ef8565fa9abdb7776f8346e17`，
  本次接受的是未提交工作区改动，不存在已接受的新 commit。
- 主管最终相关回归（13 个文件）命令：

  ```bash
  .venv/bin/python -m pytest tests/test_market_data/test_time_utils.py tests/test_tools/test_analysis.py tests/test_services/test_sector_momentum.py tests/test_backtest.py tests/test_backtest_portfolio.py tests/test_cache/test_adapter.py tests/test_agent/test_tools.py tests/test_agent/test_tools_intraday.py tests/test_web/test_mappers.py tests/test_web/test_quotes.py tests/test_install_script.py tests/test_tui_cards.py tests/test_workflow/test_definitions.py -m 'not network' -o addopts='' -q
  ```

  结果：**263 passed，1 warning，2.35s**。覆盖全仓回归采集后补充的 installer、跨时区与
  排名边界改动；此前全仓离线回归为 **2550 passed，14 deselected，3 warnings，34.46s**。
- 主管分别独立运行：`ruff format --check .`（451 files）、`ruff check .`、
  `mypy --strict src`（226 source files）、`git diff --check`，均通过。使用 `.venv/bin/`
  可执行文件，未改版本号或 uv.lock。
- 额外使用生产函数的离线断言复核（没有调用执行者测试 helper）：
  - 日 K 为 `2026-07-01T16:00Z`：三个时区表达的北京时间 7 月 2 日 10:00 均剔除，
    北京时间 15:05 均纳入；未来日期持续剔除。
  - 纽约符号 SHW、BK、^GSPC 在 `2026-11-02T00:30Z` 归属 11 月 1 日。
  - 资金流 7 月 2 日只匹配该北京交易日 close=100，不能匹配后一天 close=200。
  - 三板块参考日期为 7 月 4/5/6 日，其中一只缺 7 月 5 日：仅完整两只排名，缺失项
    有排除原因；不把窗口拉回更旧日期。
  - Web 两类资金流空输入均为 503；真实零值由相关 API 测试证明仍返回成功。
  - sequential 结果保留原简化计算，但有退出重叠、资金占用、执行时点和组合指标限制。
  - 生产 TUI bars_card 的渲染内容显示正确北京日期、旧缓存警示与复权口径。
- 验收决定：T1/T2/T3、Q1、D1 的上述局部路径、D2、R1 达到本轮检查目标；Q2 接受的是
  **诚实命名和限制披露修复，计算没有升级为真实组合模拟**。
- 剩余工作有明确再启动条件，见上表；尤其 Web stale 来源展示、并发请求级质量、供应商
  发布时点、共同缺失交易日、历史复权/PIT 与真实组合建模仍未解决或未验证。
  无法区分供应商确认空与失败的 list 契约，本轮采取“不可用”降级，没有声称完整区分。
- 未运行网络探针、真实安装升级、Docker/前端发布构建或 GitHub CI；没有发布、迁移、改写
  用户金融数据或验证用户已有报告。日期匹配修复可能改变旧回放结果，既有结果需用修复后
  版本重新生成再比较，不能沿用旧报告断言。
- `x.db` 为全仓测试新产生的已知遗留物，保持未跟踪可见；其他新增文件为本轮文档、日期
  helper 与测试。未提交、未推送。PASS 不表示全系统通过审计或任何策略具备盈利能力。

### Round 3：用户授权分支与提交

- 用户在验收后明确要求“建新分支提交”。已从起始 HEAD 创建
  `fix/systematic-correctness-review`，将本轮规范、ledger、生产修复、CHANGELOG 和测试
  一并提交；前面“未提交”的条目保留为当时状态。
- 提交前 `git diff --check` 通过；版本与 uv.lock 未改变，沿用 Round 2 验证证据。
- 显式列文件暂存，排除已知测试遗留 `x.db`；不推送、不发布、不迁移数据库。
- 提交结果以该分支 `git log -1` 为准，具体 hash 在交付消息中报告。

// 妈咪状态机：姿势 / 台词跟随 agent 活动（规则取自设计稿，工具名换成项目真实工具）。

export type Pose =
  | 'hero' | 'p_research' | 'p_up' | 'p_news' | 'p_deep'
  | 'p_win' | 'p_wait' | 'p_coffee' | 'e_think' | 'e_huh' | 'e_sleep'

export const ALL_POSES: Pose[] = [
  'hero', 'p_research', 'p_up', 'p_news', 'p_deep', 'p_win', 'p_wait', 'p_coffee', 'e_think', 'e_huh', 'e_sleep',
]

const NEWS: [Pose, string] = ['p_news', '收到！']
const UP: [Pose, string] = ['p_up', '冲！']
const DEEP: [Pose, string] = ['p_deep', '好机会！']
const RESEARCH: [Pose, string] = ['p_research', '研究中…']

/** 工具名 → 姿势 + 台词；未列出的按「研究中」 */
export const TOOL_POSES: Record<string, [Pose, string]> = {
  search_news: NEWS, get_announcements: NEWS, get_longhuban: NEWS,
  get_market_narrative: NEWS, search_similar_events: NEWS,
  get_quote: UP, get_quotes: UP, get_market_indexes: UP, get_bars: UP, get_index_bars: UP,
  get_sector_bars: UP, get_money_flow_today: UP, get_money_flow_history: UP,
  screen_inflow_stocks: DEEP, check_kline_signal: DEEP, check_earnings_catalyst: DEEP,
  get_sector_momentum: DEEP, get_sector_ranking: DEEP, market_regime_series: DEEP,
  detect_market_changes: DEEP, get_portfolio_analysis: DEEP,
}

export type Tone = 'accent' | 'run' | 'fail' | 'dim' | 'cancel'

export interface MascotView {
  pose: Pose
  say: string
  sub: string
  tone: Tone
}

export interface MascotInput {
  busy: boolean
  busyLabel: string
  /** 运行中的工具名（按开始顺序） */
  running: string[]
  /** 最早一个运行中工具已运行的毫秒数 */
  runningMs: number
  event: { kind: 'win' | 'fail' | 'stop'; ageMs: number } | null
  idleMs: number
  pokeAgeMs: number
  /** 有写操作在等用户确认 */
  awaitingConfirm?: boolean
}

const dur = (ms: number) => (ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`)

export function mascotView(s: MascotInput): MascotView {
  const ev = s.event
  if (s.busy) {
    if (s.awaitingConfirm) return { pose: 'p_wait', say: '要动手了，你确认下？', sub: 'y 允许 · n 拒绝 · a 本会话不再询问', tone: 'run' }
    if (ev?.kind === 'fail' && ev.ageMs < 1800) return { pose: 'e_huh', say: '咦？出错了', sub: '失败的步骤正在想办法', tone: 'fail' }
    if (ev?.kind === 'stop' && ev.ageMs < 4000) return { pose: 'p_wait', say: '等等…', sub: '正在中断 · 等当前步骤收尾', tone: 'cancel' }
    if (s.running.length) {
      const [pose, line] = TOOL_POSES[s.running[s.running.length - 1]] ?? RESEARCH
      return {
        pose,
        say: s.running.length > 1 ? `${line} ×${s.running.length}` : line,
        sub: `${s.running.join(' · ')} · ${dur(s.runningMs)}`,
        tone: 'run',
      }
    }
    return { pose: 'e_think', say: '让我想想…', sub: `${s.busyLabel} · 规划下一步`, tone: 'run' }
  }
  if (ev?.kind === 'win' && ev.ageMs < 4000) return { pose: 'p_win', say: '赚到了！', sub: '本轮完成 · 结果已输出', tone: 'accent' }
  if (ev?.kind === 'stop' && ev.ageMs < 4000) return { pose: 'p_wait', say: '等等…', sub: '已中断 · 等你下一步指令', tone: 'cancel' }
  if (ev?.kind === 'fail' && ev.ageMs < 4000) return { pose: 'e_huh', say: '咦？出错了', sub: '本轮出错 · 换个说法试试', tone: 'fail' }
  if (s.idleMs > 90000) return { pose: 'e_sleep', say: 'Zzz…', sub: '空闲中 · 输入任意内容叫醒我', tone: 'dim' }
  if (s.idleMs > 30000) return { pose: 'p_coffee', say: '先喝杯咖啡', sub: '空闲中', tone: 'dim' }
  if (s.pokeAgeMs < 2500) return { pose: 'hero', say: '嗨～我是妈咪！', sub: '试试 /today 或 @茅台', tone: 'accent' }
  return { pose: 'hero', say: '嗨～我是妈咪！', sub: '就绪 · 输入 / 查看命令', tone: 'accent' }
}

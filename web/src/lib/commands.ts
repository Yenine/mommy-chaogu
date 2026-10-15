// 斜杠命令：注册表 + 数据命令（调现有 REST 接口，结果渲染成设计稿的表格消息）。
// 会话 / 主题 / 面板等界面命令由 App.vue 处理，这里只登记说明。

import { getAgentHistory, getAgentInfo, listSessions } from '@/api/agent'
import type { SessionSummary } from '@/api/agent'
import { health } from '@/api/cache'
import { apiGet, toApiError } from '@/api/client'
import { fmtMoney, fmtPct, fmtPrice, getQuote, getSnapshot, getTodayMoneyFlow } from '@/api/index'
import { prettySource } from './format'
import { getIndexes } from '@/api/market'
import { getPortfolio } from '@/api/portfolio'
import { getPredictions } from '@/api/predictions'
import { recentSignals } from '@/api/signals'
import type {
  IndexQuote,
  MoneyFlowCumulative,
  MoneyFlowResponse,
  PortfolioSummary,
  Prediction,
  Quote,
  Signal,
  Snapshot,
} from '@/api/types'
import type { Msg } from './messages'

export interface Command {
  cmd: string
  arg: string
  desc: string
  /** 需要参数：菜单里 Enter 先补全「/cmd 」再等输入 */
  needs?: boolean
}

export const COMMANDS: Command[] = [
  { cmd: '/today', arg: '', desc: '今日总览：指数、自选、信号' },
  { cmd: '/usmarket', arg: '', desc: '美股大盘：标普 / 纳指 / 道指 / VIX' },
  { cmd: '/watch', arg: '', desc: '自选股行情' },
  { cmd: '/portfolio', arg: '', desc: '持仓与浮盈' },
  { cmd: '/flows', arg: '[代码]', desc: '资金流（无参数看自选主力榜）' },
  { cmd: '/quote', arg: '<代码>', desc: '个股报价（也可直接输入 6 位代码）', needs: true },
  { cmd: '/predictions', arg: '', desc: '预测跟踪' },
  { cmd: '/signals', arg: '', desc: '近期信号' },
  { cmd: '/status', arg: '', desc: '服务状态：数据源、AI 模型' },
  { cmd: '/resume', arg: '[会话ID]', desc: '恢复历史会话（与终端版共用）' },
  { cmd: '/new', arg: '', desc: '开新会话（旧会话保留在 /resume）' },
  { cmd: '/theme', arg: '[名称]', desc: '切换主题 · 不带参数列出全部' },
  { cmd: '/tools', arg: '', desc: '显示 / 隐藏工具调用时间线' },
  { cmd: '/clear', arg: '', desc: '清空对话与时间线' },
  { cmd: '/help', arg: '', desc: '查看全部命令与快捷键' },
]

export function filterCommands(input: string): Command[] {
  if (!input.startsWith('/') || input.includes(' ')) return []
  const v = input.toLowerCase()
  return COMMANDS.filter((c) => c.cmd.startsWith(v))
}

export function helpText(): string {
  return (
    COMMANDS.map((c) => `${`${c.cmd} ${c.arg}`.padEnd(22)}${c.desc}`).join('\n') +
    '\n\n快捷键  / 命令菜单 · @ 联想股票 · ↑↓ 选择 · tab 补全 · enter 执行\n' +
    '        esc 关闭菜单 / 中断当前任务 · 写操作确认时 y 允许 · n 拒绝 · a 本会话不再询问'
  )
}

const CODE_RE = /^(?:\d{6}|[A-Za-z]{1,6})$/
export const isStockCode = (s: string): boolean => CODE_RE.test(s.trim())

type Tone = 'rise' | 'fall' | ''

/** 涨跌着色：A 股红涨绿跌，美股绿涨红跌（与项目约定一致） */
export function changeTone(pct: string | number | null | undefined, market = ''): Tone {
  const n = Number(pct)
  if (!Number.isFinite(n) || n === 0) return ''
  const up = n > 0
  return market.toUpperCase() === 'US' ? (up ? 'fall' : 'rise') : up ? 'rise' : 'fall'
}

function table(header: string[], rows: string[][], tones?: Tone[][], note?: string): Msg {
  return { kind: 'table', header, rows, tones, note }
}

const yi = (s: string | null | undefined): string => (s ? fmtMoney(s, 'yi') : '—')

/** fetch 失败的统一文案：0 = 网络层失败，503 = 后台/上游暂不可用 */
const UNAVAILABLE = '行情源暂时不可用，稍后重试'

function sysFail(what: string): Msg[] {
  return [{ kind: 'sys', text: `${what}：${UNAVAILABLE}`, tone: 'fail' }]
}

/** 数据命令 fetch 失败 → 可见错误行；与「确认无数据」的空态区分，不渲染表格、不静默吞掉 */
function fetchFail(what: string, e: unknown): Msg[] {
  const err = toApiError(e, what)
  return err.status === 0 || err.status === 503
    ? sysFail(what)
    : [{ kind: 'sys', text: `${what}：${err.friendly}`, tone: 'fail' }]
}

async function today(): Promise<Msg[]> {
  const [indexesR, snapR, signalsR] = await Promise.allSettled([getIndexes(), getSnapshot(), recentSignals()])
  const out: Msg[] = []
  if (indexesR.status === 'rejected') {
    out.push(...fetchFail('指数行情', indexesR.reason))
  } else {
    const indexes = indexesR.value
    if (indexes.length) {
      out.push(
        table(
          ['指数', '点位', '涨跌'],
          indexes.slice(0, 6).map((i) => [i.name, fmtPrice(i.price), fmtPct(i.change_pct)]),
          indexes.slice(0, 6).map((i) => ['', '', changeTone(i.change_pct)]),
        ),
      )
    } else {
      // 指数是固定清单，健康时不可能为空：后端把上游失败折叠成空列表，空 ≠ 确认无数据
      out.push(...sysFail('指数行情'))
    }
  }
  if (snapR.status === 'rejected') {
    out.push(...fetchFail('自选快照', snapR.reason))
  } else {
    const snap = snapR.value
    out.push({
      kind: 'sys',
      text: `自选 ${snap.n_codes} 只 · 涨 ${snap.n_up} · 跌 ${snap.n_down} · 平 ${snap.n_flat} · 主力净额 ${yi(snap.total_main_net)}`,
    })
  }
  if (signalsR.status === 'rejected') {
    out.push(...fetchFail('近期信号', signalsR.reason))
  } else {
    const signals = signalsR.value
    out.push(
      signals.length
        ? table(
            ['时间', '代码', '名称', '信号'],
            signals.slice(0, 5).map((s) => [s.timestamp.slice(11, 16), s.code, s.name, s.title]),
          )
        : { kind: 'sys', text: '近期没有触发的信号' },
    )
  }
  return out
}

async function usMarket(): Promise<Msg[]> {
  let rows: IndexQuote[]
  try {
    rows = await apiGet<IndexQuote[]>('/api/market/us')
  } catch (e) {
    return fetchFail('美股行情', e)
  }
  if (!rows.length) return [{ kind: 'sys', text: '暂时拿不到美股数据', tone: 'warn' }]
  return [
    table(
      ['指数', '点位', '涨跌'],
      rows.map((i) => [i.name, fmtPrice(i.price), fmtPct(i.change_pct)]),
      rows.map((i) => ['', '', changeTone(i.change_pct, 'US')]),
    ),
  ]
}

async function watch(): Promise<Msg[]> {
  let snap: Snapshot
  try {
    snap = await getSnapshot()
  } catch (e) {
    return fetchFail('自选行情', e)
  }
  if (!snap.quotes.length) return [{ kind: 'sys', text: '自选股为空：告诉妈咪「把茅台加入自选」即可添加' }]
  return [
    table(
      ['代码', '名称', '现价', '涨跌', '主力净额'],
      snap.quotes.map((q) => [q.code, q.name, fmtPrice(q.price), fmtPct(q.change_pct), yi(q.main_net_inflow)]),
      snap.quotes.map((q) => ['', '', '', changeTone(q.change_pct, q.market), changeTone(q.main_net_inflow)]),
    ),
  ]
}

async function portfolio(): Promise<Msg[]> {
  let p: PortfolioSummary
  try {
    p = await getPortfolio()
  } catch (e) {
    return fetchFail('持仓', e)
  }
  if (!p.positions.length) return [{ kind: 'sys', text: '还没有持仓记录' }]
  return [
    table(
      ['代码', '名称', '数量', '成本', '现价', '浮盈'],
      p.positions.map((x) => [
        x.code,
        x.name ?? '—',
        String(x.shares),
        fmtPrice(x.avg_cost),
        x.current_price ? fmtPrice(x.current_price) : '—',
        x.unrealized_pnl_pct ? fmtPct(x.unrealized_pnl_pct) : '—',
      ]),
      p.positions.map((x) => ['', '', '', '', '', changeTone(x.unrealized_pnl_pct)]),
      `共 ${p.n_positions} 笔 · 成本 ${fmtMoney(p.total_cost, 'wan')} · 浮盈 ${
        p.total_unrealized_pnl_pct ? fmtPct(p.total_unrealized_pnl_pct) : '—'
      }`,
    ),
  ]
}

async function flows(code: string): Promise<Msg[]> {
  if (code) {
    let data: MoneyFlowResponse
    try {
      data = await getTodayMoneyFlow(code)
    } catch (e) {
      return fetchFail('资金流', e)
    }
    const c: MoneyFlowCumulative = data.cumulative
    const keys: Array<[keyof MoneyFlowCumulative, string]> = [
      ['main_net', '主力'],
      ['super_net', '超大单'],
      ['big_net', '大单'],
      ['medium_net', '中单'],
      ['small_net', '小单'],
    ]
    return [
      table(
        ['今日资金', '净额'],
        keys.map(([k, label]) => [label, yi(c[k])]),
        keys.map(([k]) => ['', changeTone(c[k])]),
        `${code} · 东方财富口径`,
      ),
    ]
  }
  let snap: Snapshot
  try {
    snap = await getSnapshot()
  } catch (e) {
    return fetchFail('自选行情', e)
  }
  const ranked = snap.quotes
    .filter((q) => q.main_net_inflow != null)
    .sort((a, b) => Math.abs(Number(b.main_net_inflow)) - Math.abs(Number(a.main_net_inflow)))
    .slice(0, 10)
  if (!ranked.length) return [{ kind: 'sys', text: '自选股暂无资金流数据' }]
  return [
    table(
      ['代码', '名称', '主力净额', '涨跌'],
      ranked.map((q) => [q.code, q.name, yi(q.main_net_inflow), fmtPct(q.change_pct)]),
      ranked.map((q) => ['', '', changeTone(q.main_net_inflow), changeTone(q.change_pct, q.market)]),
    ),
  ]
}

async function quote(code: string): Promise<Msg[]> {
  if (!isStockCode(code)) return [{ kind: 'sys', text: '用法：/quote 600519 或 /quote AAPL', tone: 'warn' }]
  let q: Quote
  try {
    q = await getQuote(code.toUpperCase())
  } catch (e) {
    return fetchFail('报价', e)
  }
  return [
    table(
      ['代码', '名称', '现价', '涨跌', '开', '高', '低', '成交额', 'PE'],
      [[q.code, q.name, fmtPrice(q.price), fmtPct(q.change_pct), fmtPrice(q.open), fmtPrice(q.high), fmtPrice(q.low), fmtMoney(q.turnover, 'yi'), q.pe ?? '—']],
      [['', '', '', changeTone(q.change_pct, q.market), '', '', '', '', '']],
      q.data_age_seconds > 600 ? `数据 ${Math.round(q.data_age_seconds / 60)} 分钟前（可能来自缓存）` : undefined,
    ),
  ]
}

async function predictions(): Promise<Msg[]> {
  let rows: Prediction[]
  try {
    rows = await getPredictions(10)
  } catch (e) {
    return fetchFail('预测记录', e)
  }
  if (!rows.length) return [{ kind: 'sys', text: '还没有预测记录：和妈咪聊个股观点时会自动记录' }]
  return [
    table(
      ['日期', '代码', '名称', '预测', '目标价', '状态'],
      rows.map((p) => [
        p.created_at.slice(0, 10),
        p.code,
        p.name ?? '—',
        p.prediction,
        p.target_price != null ? p.target_price.toFixed(2) : '—',
        String(p.status),
      ]),
    ),
  ]
}

async function signals(): Promise<Msg[]> {
  let rows: Signal[]
  try {
    rows = await recentSignals()
  } catch (e) {
    return fetchFail('近期信号', e)
  }
  if (!rows.length) return [{ kind: 'sys', text: '近期没有触发的信号' }]
  return [
    table(
      ['时间', '代码', '名称', '信号', '级别'],
      rows.slice(0, 15).map((s) => [s.timestamp.slice(5, 16).replace('T', ' '), s.code, s.name, s.title, s.severity]),
    ),
  ]
}

async function status(): Promise<Msg[]> {
  const [h, info] = await Promise.all([health().catch(() => null), getAgentInfo().catch(() => null)])
  const lines = [
    `服务     ${h?.ok ? '运行中' : '不可用'}${h ? ` · 已运行 ${Math.round(h.uptime_seconds / 60)} 分钟` : ''}`,
    `数据源   ${h?.adapter_name ? prettySource(h.adapter_name) : '—'}`,
    // info 为 null 是读取失败（≠ 未配置），不能提示用户去 setup
    `AI       ${info ? (info.configured ? `${info.provider} · ${info.model}` : '未配置（在终端运行 mommy setup）') : '暂不可用'}`,
  ]
  return [{ kind: 'sys', text: lines.join('\n') }]
}

async function sessions(): Promise<Msg[]> {
  let rows: SessionSummary[]
  try {
    rows = await listSessions(15)
  } catch (e) {
    return fetchFail('会话列表', e)
  }
  if (!rows.length) return [{ kind: 'sys', text: '暂无可恢复的会话' }]
  return [
    table(
      ['会话ID', '条数', '最近活跃', '最近的问题'],
      rows.map((s) => [s.session_id, String(s.messages), s.last_active.slice(5, 16).replace('T', ' '), s.preview || '—']),
      undefined,
      '/resume <会话ID> 继续这段对话',
    ),
  ]
}

/** 数据命令：返回要追加到对话流的消息；不认识的命令返回 null（交给 App 处理） */
export async function runDataCommand(cmd: string, args: string[]): Promise<Msg[] | null> {
  const a0 = (args[0] ?? '').trim()
  switch (cmd) {
    case '/today':
      return today()
    case '/usmarket':
      return usMarket()
    case '/watch':
      return watch()
    case '/portfolio':
      return portfolio()
    case '/flows':
      return flows(a0)
    case '/quote':
      return quote(a0)
    case '/predictions':
      return predictions()
    case '/signals':
      return signals()
    case '/status':
      return status()
    case '/resume':
      return a0 ? null : sessions()
    default:
      return null
  }
}

/** 会话历史 → 对话流消息（/resume、刷新页面后恢复） */
export async function historyMessages(limit = 40): Promise<Msg[]> {
  const rows = await getAgentHistory(limit)
  return rows
    .filter((m) => m.role === 'user' || m.role === 'assistant')
    .map((m): Msg => (m.role === 'user' ? { kind: 'user', text: m.content } : { kind: 'text', text: m.content }))
}

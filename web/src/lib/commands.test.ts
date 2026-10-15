import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiGet = vi.fn()
vi.mock('@/api/client', async (importOriginal) => ({
  // 保留 ApiError / toApiError 真实现（commands.ts 的错误态渲染依赖它们）
  ...(await importOriginal<typeof import('@/api/client')>()),
  apiGet: (path: string) => apiGet(path),
  apiPost: vi.fn(),
  getChatSessionId: () => 'web-test',
}))

import { ApiError } from '@/api/client'
import { COMMANDS, changeTone, filterCommands, helpText, isStockCode, runDataCommand } from './commands'

beforeEach(() => apiGet.mockReset())

describe('斜杠命令', () => {
  it('菜单按前缀过滤，带空格即关闭', () => {
    expect(filterCommands('/t').map((c) => c.cmd)).toEqual(['/today', '/theme', '/tools'])
    expect(filterCommands('/quote 6')).toEqual([])
    expect(filterCommands('hello')).toEqual([])
    expect(filterCommands('/').length).toBe(COMMANDS.length)
  })

  it('帮助列出全部命令与快捷键', () => {
    const text = helpText()
    for (const c of COMMANDS) expect(text).toContain(c.cmd)
    expect(text).toContain('a 本会话不再询问')
  })

  it('A 股红涨绿跌，美股反过来', () => {
    expect(changeTone('1.2')).toBe('rise')
    expect(changeTone('-1.2')).toBe('fall')
    expect(changeTone('1.2', 'US')).toBe('fall')
    expect(changeTone('0')).toBe('')
    expect(changeTone(null)).toBe('')
  })

  it('股票代码识别', () => {
    expect(isStockCode('600519')).toBe(true)
    expect(isStockCode('AAPL')).toBe(true)
    expect(isStockCode('茅台')).toBe(false)
  })

  it('/quote 渲染成一行表格并按涨跌着色', async () => {
    apiGet.mockResolvedValueOnce({
      code: '600519', name: '贵州茅台', market: 'SH', price: '1680.5', change_pct: '1.85', open: '1660', high: '1690',
      low: '1655', turnover: '2000000000', pe: '25.6', data_age_seconds: 3,
    })
    const [msg] = (await runDataCommand('/quote', ['600519']))!
    expect(apiGet).toHaveBeenCalledWith('/api/quotes/600519')
    expect(msg).toMatchObject({ kind: 'table' })
    if (msg.kind !== 'table') throw new Error('expected table')
    expect(msg.rows[0].slice(0, 4)).toEqual(['600519', '贵州茅台', '1680.50', '+1.85%'])
    expect(msg.tones?.[0][3]).toBe('rise')
    expect(msg.note).toBeUndefined()
  })

  it('/quote 没给代码给用法提示，不请求接口', async () => {
    const [msg] = (await runDataCommand('/quote', []))!
    expect(msg).toMatchObject({ kind: 'sys', tone: 'warn' })
    expect(apiGet).not.toHaveBeenCalled()
  })

  it('/resume 列表；带 ID 交给页面处理', async () => {
    apiGet.mockResolvedValueOnce({
      sessions: [{ session_id: 'web-abc', messages: 4, last_active: '2026-10-14T03:33:00', preview: '茅台怎么样' }],
    })
    const [msg] = (await runDataCommand('/resume', []))!
    if (msg.kind !== 'table') throw new Error('expected table')
    expect(msg.rows[0]).toEqual(['web-abc', '4', '10-14 03:33', '茅台怎么样'])
    expect(await runDataCommand('/resume', ['web-abc'])).toBeNull()
  })

  it('/flows 无参数按主力净额绝对值排序', async () => {
    apiGet.mockResolvedValueOnce({
      quotes: [
        { code: 'A', name: 'a', market: 'SH', change_pct: '1', main_net_inflow: '100000000' },
        { code: 'B', name: 'b', market: 'SH', change_pct: '-1', main_net_inflow: '-500000000' },
        { code: 'C', name: 'c', market: 'SH', change_pct: '0', main_net_inflow: null },
      ],
    })
    const [msg] = (await runDataCommand('/flows', []))!
    if (msg.kind !== 'table') throw new Error('expected table')
    expect(msg.rows.map((r) => r[0])).toEqual(['B', 'A'])
    expect(msg.rows[0][2]).toBe('-5.00亿')
  })

  it('/flows <代码> 渲染当日累计表', async () => {
    apiGet.mockResolvedValueOnce({
      items: [],
      cumulative: { main_net: '120000000', super_net: '80000000', big_net: '40000000', medium_net: '-10000000', small_net: '-5000000' },
    })
    const [msg] = (await runDataCommand('/flows', ['600519']))!
    expect(apiGet).toHaveBeenCalledWith('/api/quotes/600519/money_flow/today')
    if (msg.kind !== 'table') throw new Error('expected table')
    expect(msg.rows).toEqual([
      ['主力', '1.20亿'],
      ['超大单', '0.80亿'],
      ['大单', '0.40亿'],
      ['中单', '-0.10亿'],
      ['小单', '-0.05亿'],
    ])
  })

  it('fetch 失败渲染可见错误行，不渲染 0 值表格（上游空/失败 → 503）', async () => {
    apiGet.mockRejectedValueOnce(
      new ApiError(503, '服务暂时不可用', 'GET /api/quotes/600519/money_flow/today → 503'),
    )
    const msgs = (await runDataCommand('/flows', ['600519']))!
    expect(msgs).toEqual([{ kind: 'sys', text: '资金流 600519：行情源暂时不可用，稍后重试', tone: 'fail' }])
  })

  it('网络层失败（TypeError）同样渲染不可用错误行', async () => {
    apiGet.mockRejectedValueOnce(new TypeError('fetch failed'))
    const msgs = (await runDataCommand('/watch', []))!
    expect(msgs).toEqual([{ kind: 'sys', text: '自选行情：行情源暂时不可用，稍后重试', tone: 'fail' }])
  })

  it('非 503 的失败用具体文案，不误报行情源；文案回显所查代码', async () => {
    apiGet.mockRejectedValueOnce(new ApiError(404, '没有找到', 'GET /api/quotes/999999 → 404'))
    const msgs = (await runDataCommand('/quote', ['999999']))!
    expect(msgs).toEqual([{ kind: 'sys', text: '报价 999999：没有找到', tone: 'fail' }])
  })

  it('/quote 空壳行情（现价 0）显示 — 而非误导性的 0.00', async () => {
    apiGet.mockResolvedValueOnce({
      code: '601989', name: '中国重工', market: 'SH', price: '0', change_pct: '0', open: '0', high: '0',
      low: '0', turnover: '0', pe: null, data_age_seconds: 3,
    })
    const [msg] = (await runDataCommand('/quote', ['601989']))!
    if (msg.kind !== 'table') throw new Error('expected table')
    expect(msg.rows[0].slice(2, 7)).toEqual(['—', '—', '—', '—', '—'])
  })

  it('/watch 现价 0 的行（停牌 / 退市代码缓存）价格与涨跌显示 —', async () => {
    apiGet.mockResolvedValueOnce({
      quotes: [
        { code: '600519', name: '贵州茅台', market: 'SH', price: '1680.5', change_pct: '1.2', main_net_inflow: '100000000' },
        { code: '601989', name: '中国重工', market: 'SH', price: '0', change_pct: '0', main_net_inflow: null },
      ],
    })
    const [msg] = (await runDataCommand('/watch', []))!
    if (msg.kind !== 'table') throw new Error('expected table')
    expect(msg.rows[1]).toEqual(['601989', '中国重工', '—', '—', '—'])
    expect(msg.rows[0].slice(2, 4)).toEqual(['1680.50', '+1.20%'])
  })

  it('/today 部分源失败：失败源给错误行，成功源照常，空态仍是「没有信号」', async () => {
    apiGet
      .mockRejectedValueOnce(new TypeError('fetch failed'))
      .mockResolvedValueOnce({ n_codes: 2, n_up: 1, n_down: 1, n_flat: 0, total_main_net: '300000000', quotes: [] })
      .mockResolvedValueOnce([])
    const msgs = (await runDataCommand('/today', []))!
    expect(msgs).toEqual([
      { kind: 'sys', text: '指数行情：行情源暂时不可用，稍后重试', tone: 'fail' },
      { kind: 'sys', text: '自选 2 只 · 涨 1 · 跌 1 · 平 0 · 主力净额 3.00亿' },
      { kind: 'sys', text: '近期没有触发的信号' },
    ])
  })

  it('界面命令不在数据命令里处理', async () => {
    expect(await runDataCommand('/theme', ['nord'])).toBeNull()
    expect(await runDataCommand('/clear', [])).toBeNull()
  })
})

import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiGet = vi.fn()
vi.mock('@/api/client', () => ({
  apiGet: (path: string) => apiGet(path),
  apiPost: vi.fn(),
  getChatSessionId: () => 'web-test',
}))

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

  it('界面命令不在数据命令里处理', async () => {
    expect(await runDataCommand('/theme', ['nord'])).toBeNull()
    expect(await runDataCommand('/clear', [])).toBeNull()
  })
})

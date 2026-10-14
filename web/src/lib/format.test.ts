import { describe, expect, it } from 'vitest'
import { argStr, argsJson, cellTone, digest, fmtDur, prettySource, shortSession, thousands } from './format'

describe('format', () => {
  it('fmtDur 与终端版一致：850ms / 1.2s', () => {
    expect(fmtDur(850)).toBe('850ms')
    expect(fmtDur(1234)).toBe('1.2s')
    expect(fmtDur(-5)).toBe('0ms')
  })

  it('argStr 按设计稿格式：key: JSON 值，数组展开', () => {
    expect(argStr({ symbol: '300750.SZ', days: 7, types: ['定期报告'] })).toBe(
      'symbol: "300750.SZ", days: 7, types: [定期报告]',
    )
    expect(argStr(undefined)).toBe('')
    expect(argsJson({ a: 1 })).toBe('{ "a": 1 }')
  })

  it('cellTone：+ 为涨、-数字 为跌', () => {
    expect(cellTone('+2.4pp')).toBe('up')
    expect(cellTone('-0.64%')).toBe('down')
    expect(cellTone('-')).toBe('')
  })

  it('digest 取首个非空行并截断', () => {
    expect(digest('\n  贵州茅台 1680\n第二行')).toBe('贵州茅台 1680')
    expect(digest('x'.repeat(100), 10)).toBe(`${'x'.repeat(9)}…`)
    expect(digest(null)).toBe('')
  })

  it('数据源标签与会话 ID 转人话', () => {
    expect(prettySource('cached(fallback(massive,yahoo,efinance))')).toBe('massive · yahoo · efinance')
    expect(prettySource('efinance')).toBe('efinance')
    expect(shortSession('web-b301997d-0e20-4f5c-a132-1c6cc95a715a')).toBe('b301997d')
    expect(shortSession('tui-default')).toBe('tui-default')
    expect(thousands(24420)).toBe('24,420')
  })
})

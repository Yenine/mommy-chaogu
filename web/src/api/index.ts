// 行情 API
import { apiGet } from './client'
import type { Quote, Snapshot, MoneyFlowResponse } from './types'

export function getSnapshot(): Promise<Snapshot> {
  return apiGet('/api/quotes')
}

export function getQuote(code: string): Promise<Quote> {
  return apiGet(`/api/quotes/${code}`)
}

export function getTodayMoneyFlow(code: string): Promise<MoneyFlowResponse> {
  return apiGet(`/api/quotes/${code}/money_flow/today`)
}

// 格式化辅助
export function fmtMoney(s: string | null | undefined, unit: 'yuan' | 'wan' | 'yi' = 'yuan'): string {
  if (!s) return '-'
  const n = Number(s)
  if (isNaN(n)) return s
  if (unit === 'yi') return `${(n / 1e8).toFixed(2)}亿`
  if (unit === 'wan') return `${(n / 1e4).toFixed(2)}万`
  return n.toFixed(2)
}

export function fmtPrice(s: string): string {
  const n = Number(s)
  if (isNaN(n)) return s
  return n.toFixed(2)
}

export function fmtPct(s: string): string {
  const n = Number(s)
  if (isNaN(n)) return s
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
}

// 市场排行 API
import { apiGet } from './client'
import type { IndexQuote, StockSearchResult } from './types'

export function getIndexes(): Promise<IndexQuote[]> {
  return apiGet('/api/market/indexes')
}

export function searchStocks(query: string, limit = 10): Promise<StockSearchResult[]> {
  const params = new URLSearchParams({ q: query, limit: String(limit) })
  return apiGet(`/api/stocks/search?${params}`)
}

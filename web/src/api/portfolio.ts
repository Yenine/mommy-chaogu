// 持仓 API
import { apiGet } from './client'
import type { PortfolioSummary } from './types'

export function getPortfolio(): Promise<PortfolioSummary> {
  return apiGet('/api/portfolio')
}

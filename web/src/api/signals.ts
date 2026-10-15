// 信号 API
import { apiGet } from './client'
import type { Signal } from './types'

export function recentSignals(): Promise<Signal[]> {
  return apiGet('/api/signals/recent')
}

// 缓存 API
import { apiGet } from './client'
import type { Health } from './types'

export function health(): Promise<Health> {
  return apiGet('/api/health')
}

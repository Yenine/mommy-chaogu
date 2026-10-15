// 预测跟踪 API — agent 记忆系统的预测命中率闭环
import { apiGet } from './client'
import type { Prediction } from './types'

/** 获取最近 limit 条预测记录（按 created_at 降序）。 */
export function getPredictions(limit = 20): Promise<Prediction[]> {
  return apiGet<{ predictions: Prediction[]; total: number }>(
    `/api/agent/predictions?limit=${limit}`,
  ).then((r) => r.predictions)
}

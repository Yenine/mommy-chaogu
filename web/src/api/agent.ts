// Agent API client
import { apiGet, apiPost, getChatSessionId } from './client'
import type { AgentHistoryMessage } from './types'

export interface RouteStep {
  name: string
  tool: string
  success: boolean
  /** 本步耗时（毫秒）；后端 engine 计时，供时间线展示 */
  elapsed_ms?: number
}

export interface RouteResponse {
  matched: boolean
  workflow_id?: string
  reply?: string
  steps?: RouteStep[]
}

export async function agentRoute(
  message: string,
  sessionId?: string,
  signal?: AbortSignal,
): Promise<RouteResponse> {
  return apiPost<RouteResponse>(
    '/api/agent/route',
    { message, session_id: sessionId ?? getChatSessionId() },
    signal,
  )
}

export function getAgentHistory(limit = 50): Promise<AgentHistoryMessage[]> {
  const sessionId = encodeURIComponent(getChatSessionId())
  return apiGet<{ messages: AgentHistoryMessage[]; total: number }>(
    `/api/agent/history?session_id=${sessionId}&limit=${limit}`,
  ).then((response) => response.messages)
}

export interface SessionSummary {
  session_id: string
  messages: number
  last_active: string
  preview: string
}

/** GET /api/agent/sessions 响应（契约对照用；见 tests/test_web/test_frontend_contract.py） */
export interface SessionsResponse {
  sessions: SessionSummary[]
}

/** 可恢复的历史会话（/resume；与终端版共用记忆库） */
export function listSessions(limit = 20): Promise<SessionSummary[]> {
  return apiGet<SessionsResponse>(`/api/agent/sessions?limit=${limit}`).then(
    (response) => response.sessions,
  )
}

export interface AgentInfo {
  configured: boolean
  provider: string
  model: string
}

/** 当前 AI 配置（是否配置 / provider / model，不含密钥） */
export function getAgentInfo(): Promise<AgentInfo> {
  return apiGet<AgentInfo>('/api/agent/info')
}

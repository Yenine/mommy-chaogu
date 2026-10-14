// Agent API client
import { apiGet, apiPost, getChatSessionId } from './client'
import type { AgentHistoryMessage } from './types'

export interface ChatResponse {
  reply: string
  tools_used: string[]
  rounds: number
}

export interface AgentPageContext {
  surface: 'stock'
  stock_code: string
  tab: 'overview' | 'chart' | 'flow' | 'decisions'
  basket_id?: string
  quote_as_of?: string
}

export interface RouteStep {
  name: string
  tool: string
  success: boolean
}

export interface RouteResponse {
  matched: boolean
  workflow_id?: string
  reply?: string
  steps?: RouteStep[]
}

export type AgentStreamState = 'connecting' | 'connected' | 'disconnected'

/** 工具调用事件（后端 ws.py 推送） */
export interface ToolCallEvent {
  tool: string
  args?: Record<string, unknown>
}
export interface ToolResultEvent {
  tool: string
  status: 'done' | 'fail'
  elapsedMs: number
  result?: string
}

/** done 之后由后台记忆抽取产生的预测（ws.py 推送） */
export interface PredictionsCreatedEvent {
  count: number
  predictions: { id: number; code: string; name: string | null }[]
}

export async function agentChat(
  message: string,
  history?: Array<{ role: string; content: string }>,
  pageContext?: AgentPageContext,
): Promise<ChatResponse> {
  return apiPost<ChatResponse>('/api/agent/chat', {
    message,
    history,
    session_id: getChatSessionId(),
    page_context: pageContext,
  })
}

export async function agentRoute(
  message: string,
  signal?: AbortSignal,
): Promise<RouteResponse> {
  return apiPost<RouteResponse>('/api/agent/route', { message }, signal)
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

/** 可恢复的历史会话（/resume；与终端版共用记忆库） */
export function listSessions(limit = 20): Promise<SessionSummary[]> {
  return apiGet<{ sessions: SessionSummary[] }>(`/api/agent/sessions?limit=${limit}`).then(
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

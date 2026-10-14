// 对话流消息模型（设计稿 msgs：user / text / sys / tool / table，外加确认条与思考块）。

import type { Decision } from './agentSocket'

export type Msg =
  | { kind: 'user'; text: string }
  | { kind: 'text'; text: string; streaming?: boolean; interrupted?: boolean }
  | { kind: 'sys'; text: string; tone?: 'dim' | 'warn' | 'fail' }
  | { kind: 'tool'; id: string }
  | { kind: 'table'; header: string[]; rows: string[][]; note?: string; tones?: Array<Array<'rise' | 'fall' | ''>> }
  | { kind: 'thinking'; text: string; done: boolean; startedAt: number; ms?: number; open?: boolean }
  | {
      kind: 'confirm'
      id: string
      tool: string
      description: string
      args: Record<string, unknown>
      decision?: Decision | 'cancelled'
    }

export type ToolStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'denied'

/** 时间线 / 对话流共用的一次工具调用（或工作流步骤） */
export interface ToolCall {
  id: string
  turn: number
  name: string
  args: Record<string, unknown>
  status: ToolStatus
  start?: number
  end?: number
  result?: string
}

export interface TurnInfo {
  label: string
  start: number
}

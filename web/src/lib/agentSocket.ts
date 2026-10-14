// /ws/agent 客户端：一轮对话的全部事件 + 控制消息（写操作确认 / Esc 中断）。
// 协议见后端 src/mommy_chaogu/web/routes/ws.py 的 ws_agent 文档。

import { authenticatedWsUrl } from '@/api/client'

export type Decision = 'allow' | 'deny' | 'always'

export interface AgentHandlers {
  thinking?: () => void
  thinkingDelta?: (text: string) => void
  toolStarted?: (tool: string, args: Record<string, unknown>) => void
  toolFinished?: (tool: string, ok: boolean, elapsedMs: number, result: string) => void
  confirm?: (req: { id: string; tool: string; args: Record<string, unknown>; description: string }) => void
  retry?: (attempt: number, max: number) => void
  chunk?: (text: string) => void
  usage?: (u: { prompt_tokens: number; completion_tokens: number; total_tokens: number }) => void
  interrupted?: () => void
  /** 本轮结束（正常完成、被中断、出错或断线都会调用一次） */
  done?: (info: { text: string; error?: string }) => void
  predictions?: (count: number) => void
}

type SocketFactory = (url: string) => WebSocket

export class AgentSocket {
  private ws: WebSocket | null = null
  private opening: Promise<WebSocket> | null = null
  private inTurn = false

  constructor(
    private readonly handlers: AgentHandlers,
    private readonly makeSocket: SocketFactory = (url) => new WebSocket(url),
    private readonly urlFor: (path: string) => Promise<string> = authenticatedWsUrl,
  ) {}

  /** 发起一轮对话（连接按需建立，断线后下次自动重连） */
  async send(message: string, sessionId: string): Promise<void> {
    this.inTurn = true
    try {
      const ws = await this.connect()
      ws.send(JSON.stringify({ message, session_id: sessionId }))
    } catch (error) {
      this.finish({ text: '', error: error instanceof Error ? error.message : '连接失败' })
    }
  }

  confirm(id: string, decision: Decision): void {
    this.control({ type: 'confirm', id, decision })
  }

  /** Esc：中断当前轮（后端把待决确认按拒绝落定） */
  cancel(): void {
    this.control({ type: 'cancel' })
  }

  close(): void {
    this.ws?.close()
    this.ws = null
  }

  private control(payload: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(payload))
  }

  private finish(info: { text: string; error?: string }): void {
    if (!this.inTurn) return
    this.inTurn = false
    this.handlers.done?.(info)
  }

  private connect(): Promise<WebSocket> {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return Promise.resolve(this.ws)
    if (this.opening) return this.opening
    this.opening = (async () => {
      const url = await this.urlFor('/ws/agent')
      const ws = this.makeSocket(url)
      await new Promise<void>((resolve, reject) => {
        ws.onopen = () => resolve()
        ws.onerror = () => reject(new Error('WebSocket 连接失败，请确认服务正在运行'))
      })
      ws.onmessage = (event) => this.dispatch(String(event.data))
      ws.onclose = () => {
        if (this.ws === ws) this.ws = null
        this.finish({ text: '', error: '连接已断开' })
      }
      ws.onerror = () => {}
      this.ws = ws
      return ws
    })().finally(() => {
      this.opening = null
    })
    return this.opening
  }

  private dispatch(raw: string): void {
    let msg: Record<string, any>
    try {
      msg = JSON.parse(raw)
    } catch {
      return
    }
    const h = this.handlers
    switch (msg.type) {
      case 'thinking':
        h.thinking?.()
        break
      case 'thinking_delta':
        h.thinkingDelta?.(String(msg.text ?? ''))
        break
      case 'tool_call_started':
        h.toolStarted?.(String(msg.tool), (msg.args ?? {}) as Record<string, unknown>)
        break
      case 'tool_call_finished':
        h.toolFinished?.(String(msg.tool), msg.status !== 'fail', Number(msg.elapsed_ms ?? 0), String(msg.result ?? ''))
        break
      case 'confirm_required':
        h.confirm?.({ id: String(msg.id), tool: String(msg.tool), args: msg.args ?? {}, description: String(msg.description ?? msg.tool) })
        break
      case 'retry':
        h.retry?.(Number(msg.attempt ?? 1), Number(msg.max ?? 1))
        break
      case 'chunk':
        h.chunk?.(String(msg.text ?? ''))
        break
      case 'usage':
        h.usage?.({
          prompt_tokens: Number(msg.prompt_tokens ?? 0),
          completion_tokens: Number(msg.completion_tokens ?? 0),
          total_tokens: Number(msg.total_tokens ?? 0),
        })
        break
      case 'interrupted':
        h.interrupted?.()
        break
      case 'done':
        this.finish({ text: String(msg.text ?? '') })
        break
      case 'predictions_created':
        h.predictions?.(Number(msg.count ?? 0))
        break
      case 'error':
        this.finish({ text: '', error: String(msg.message ?? '未知错误') })
        break
    }
  }
}

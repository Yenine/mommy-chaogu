import { describe, expect, it, vi } from 'vitest'
import { AgentSocket } from './agentSocket'

class FakeWS {
  static OPEN = 1
  readyState = 0
  sent: string[] = []
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  send(d: string) { this.sent.push(d) }
  close() { this.readyState = 3; this.onclose?.() }
  open() { this.readyState = 1; this.onopen?.() }
  emit(msg: object) { this.onmessage?.({ data: JSON.stringify(msg) }) }
}

function setup() {
  ;(globalThis as any).WebSocket = { OPEN: 1 }
  const sockets: FakeWS[] = []
  const handlers = {
    toolStarted: vi.fn(), toolFinished: vi.fn(), confirm: vi.fn(), chunk: vi.fn(), usage: vi.fn(),
    interrupted: vi.fn(), done: vi.fn(), thinkingDelta: vi.fn(), retry: vi.fn(), predictions: vi.fn(),
  }
  const agent = new AgentSocket(
    handlers,
    () => {
      const ws = new FakeWS()
      sockets.push(ws)
      queueMicrotask(() => ws.open())
      return ws as unknown as WebSocket
    },
    async () => 'ws://test/ws/agent',
  )
  return { agent, sockets, handlers }
}

describe('AgentSocket', () => {
  it('发消息、分发全部事件、done 结束本轮', async () => {
    const { agent, sockets, handlers } = setup()
    await agent.send('茅台', 'web-1')
    const ws = sockets[0]
    expect(JSON.parse(ws.sent[0])).toEqual({ message: '茅台', session_id: 'web-1' })
    ws.emit({ type: 'thinking_delta', text: '想' })
    ws.emit({ type: 'tool_call_started', tool: 'get_quote', args: { code: '600519' } })
    ws.emit({ type: 'tool_call_finished', tool: 'get_quote', status: 'fail', elapsed_ms: 12, result: 'x' })
    ws.emit({ type: 'confirm_required', id: 'c1', tool: 'manage_watchlist', args: {}, description: '修改自选股' })
    ws.emit({ type: 'retry', attempt: 1, max: 2 })
    ws.emit({ type: 'chunk', text: '答' })
    ws.emit({ type: 'usage', prompt_tokens: 1, completion_tokens: 2, total_tokens: 3 })
    ws.emit({ type: 'interrupted' })
    ws.emit({ type: 'done', tools_used: [], rounds: 1 })
    expect(handlers.thinkingDelta).toHaveBeenCalledWith('想')
    expect(handlers.toolStarted).toHaveBeenCalledWith('get_quote', { code: '600519' })
    expect(handlers.toolFinished).toHaveBeenCalledWith('get_quote', 'failed', 12, 'x')
    expect(handlers.confirm).toHaveBeenCalledWith(expect.objectContaining({ id: 'c1', description: '修改自选股' }))
    expect(handlers.retry).toHaveBeenCalledWith(1, 2)
    expect(handlers.chunk).toHaveBeenCalledWith('答')
    expect(handlers.usage).toHaveBeenCalledWith({ prompt_tokens: 1, completion_tokens: 2, total_tokens: 3 })
    expect(handlers.interrupted).toHaveBeenCalled()
    expect(handlers.done).toHaveBeenCalledTimes(1)
  })

  it('denied 状态透传给 toolFinished（写操作被拒 ≠ 失败）', async () => {
    const { agent, sockets, handlers } = setup()
    await agent.send('存策略卡', 'web-1')
    sockets[0].emit({ type: 'tool_call_finished', tool: 'strategy_save', status: 'denied', elapsed_ms: 0, result: '用户拒绝了该操作' })
    sockets[0].emit({ type: 'tool_call_finished', tool: 'get_quote', status: 'done', elapsed_ms: 5, result: '{"price": 1}' })
    expect(handlers.toolFinished).toHaveBeenNthCalledWith(1, 'strategy_save', 'denied', 0, '用户拒绝了该操作')
    expect(handlers.toolFinished).toHaveBeenNthCalledWith(2, 'get_quote', 'done', 5, '{"price": 1}')
  })

  it('确认与中断走同一连接', async () => {
    const { agent, sockets } = setup()
    await agent.send('加自选', 'web-1')
    agent.confirm('c1', 'always')
    agent.cancel()
    expect(sockets[0].sent.slice(1).map((s) => JSON.parse(s))).toEqual([
      { type: 'confirm', id: 'c1', decision: 'always' },
      { type: 'cancel' },
    ])
  })

  it('本轮中断线：结束本轮并报错，下次发送自动重连', async () => {
    const { agent, sockets, handlers } = setup()
    await agent.send('a', 's')
    sockets[0].close()
    expect(handlers.done).toHaveBeenCalledWith({ text: '', error: '连接已断开' })
    await agent.send('b', 's')
    expect(sockets).toHaveLength(2)
  })

  it('error 事件结束本轮', async () => {
    const { agent, sockets, handlers } = setup()
    await agent.send('a', 's')
    sockets[0].emit({ type: 'error', message: 'AI 助手忙，请稍后重试' })
    expect(handlers.done).toHaveBeenCalledWith({ text: '', error: 'AI 助手忙，请稍后重试' })
  })
})

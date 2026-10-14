<script setup lang="ts">
// 妈咪炒股 · 网页版：Claude Design「Research Agent TUI」设计稿的正式实现（整站单页）。
// 左：欢迎卡 + 对话流 + / 命令菜单 + 输入框 + 底栏；右：妈咪 + 工具调用时间线。
// 后端：/api/agent/route（预定义工作流）→ 未命中走 /ws/agent 流式对话；斜杠命令走 REST。
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { agentRoute, getAgentInfo } from '@/api/agent'
import { health } from '@/api/cache'
import {
  getChatSessionId,
  loadAuthStatus,
  resetChatSessionId,
  setChatSessionId,
  toApiError,
} from '@/api/client'
import { searchStocks } from '@/api/market'
import { submitPairingCode } from '@/api/setup'
import type { StockSearchResult } from '@/api/types'
import MascotPanel from '@/components/MascotPanel.vue'
import ToolTimeline from '@/components/ToolTimeline.vue'
import { AgentSocket, type Decision } from '@/lib/agentSocket'
import {
  COMMANDS,
  filterCommands,
  helpText,
  historyMessages,
  isStockCode,
  runDataCommand,
  type Command,
} from '@/lib/commands'
import { argStr, cellTone, digest, fmtDur, prettySource, shortSession, thousands } from '@/lib/format'
import { mascotView } from '@/lib/mascot'
import type { Msg, ToolCall, TurnInfo } from '@/lib/messages'
import { THEME_LABELS, isTheme, loadTheme, saveTheme, themeList, type ThemeName } from '@/lib/themes'

const SPIN = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
const PANEL_W = 420

// ---------------------------------------------------------------- 状态
const msgs = ref<Msg[]>([])
const tools = ref<ToolCall[]>([])
const turns = reactive<Record<number, TurnInfo>>({})
let turnNo = 0
let uid = 0

const busy = ref(false)
const busyLabel = ref('')
const busyStart = ref(0)
const retryNote = ref('')
const queue = ref<string[]>([])
const tick = ref(0)
const now = ref(Date.now())

const input = ref('')
const sel = ref(0)
const menuDismissed = ref(false)
const stockHits = ref<StockSearchResult[]>([])
const sent: string[] = []
let histIdx = -1

const theme = ref<ThemeName>(loadTheme())
const showTimeline = ref(true)
const narrow = ref(false)
const tokens = ref(0)
const selTool = ref<string | null>(null)

const auth = ref<'loading' | 'ok' | 'pairing' | 'offline'>('loading')
const llmConfigured = ref(true)
const modelLabel = ref('')
const dataSource = ref('')
const sessionId = ref(getChatSessionId())

const mascotEvent = ref<{ kind: 'win' | 'fail' | 'stop'; at: number } | null>(null)
let lastActive = Date.now()
let poked = -1e9

const inputEl = ref<HTMLInputElement | null>(null)
const scrollEl = ref<HTMLDivElement | null>(null)

// 当前轮的流式状态
let answerIdx: number | null = null
let thinkingIdx: number | null = null
let turnFailed = false
let turnInterrupted = false

// ---------------------------------------------------------------- 后端事件
const agent = new AgentSocket({
  thinkingDelta(text) {
    if (thinkingIdx === null) {
      msgs.value.push({ kind: 'thinking', text: '', done: false, startedAt: Date.now() })
      thinkingIdx = msgs.value.length - 1
    }
    const m = msgs.value[thinkingIdx]
    if (m.kind === 'thinking') m.text += text
  },
  toolStarted(name, args) {
    closeThinking()
    answerIdx = null
    retryNote.value = ''
    const t: ToolCall = { id: `t${++uid}`, turn: turnNo, name, args, status: 'running', start: Date.now() }
    tools.value.push(t)
    msgs.value.push({ kind: 'tool', id: t.id })
  },
  toolFinished(name, status, elapsedMs, result) {
    const t = tools.value.find((x) => x.turn === turnNo && x.name === name && x.status === 'running')
    if (!t) return
    t.end = elapsedMs && t.start ? t.start + elapsedMs : Date.now()
    t.result = result
    t.status = status
    if (t.status === 'failed') mascotEvent.value = { kind: 'fail', at: Date.now() }
  },
  confirm(req) {
    msgs.value.push({ kind: 'confirm', ...req })
  },
  retry(attempt, max) {
    retryNote.value = `⏳ 网络较慢，正在重试 (${attempt}/${max})…`
  },
  chunk(text) {
    closeThinking()
    retryNote.value = ''
    if (answerIdx === null) {
      msgs.value.push({ kind: 'text', text: '', streaming: true })
      answerIdx = msgs.value.length - 1
    }
    const m = msgs.value[answerIdx]
    if (m.kind === 'text') m.text += text
  },
  usage(u) {
    tokens.value += u.total_tokens
  },
  interrupted() {
    turnInterrupted = true
  },
  done({ text, error }) {
    if (error) {
      turnFailed = true
      msgs.value.push({ kind: 'sys', text: `✗ ${error}`, tone: 'fail' })
    } else if (text && answerIdx === null) {
      msgs.value.push({ kind: 'text', text })
    }
    endTurn()
  },
  predictions(count) {
    if (count > 0) msgs.value.push({ kind: 'sys', text: `📌 已记录 ${count} 条预测（/predictions 查看）`, tone: 'dim' })
  },
})

function closeThinking() {
  if (thinkingIdx === null) return
  const m = msgs.value[thinkingIdx]
  if (m.kind === 'thinking' && !m.done) {
    m.done = true
    m.ms = Date.now() - m.startedAt
  }
}

function beginTurn(text: string, label: string) {
  turnNo += 1
  turns[turnNo] = { label: text, start: Date.now() }
  busy.value = true
  busyLabel.value = label
  busyStart.value = Date.now()
  retryNote.value = ''
  answerIdx = null
  thinkingIdx = null
  turnFailed = false
  turnInterrupted = false
  mascotEvent.value = null
  lastActive = Date.now()
}

function endTurn() {
  closeThinking()
  for (const m of msgs.value) {
    if (m.kind === 'text' && m.streaming) {
      m.streaming = false
      if (turnInterrupted && m.text) m.interrupted = true
    }
    if (m.kind === 'confirm' && !m.decision) m.decision = 'cancelled'
  }
  for (const t of tools.value) {
    if (t.status === 'running') {
      t.status = 'cancelled'
      t.end = Date.now()
    }
  }
  busy.value = false
  retryNote.value = ''
  lastActive = Date.now()
  if (!turnInterrupted) mascotEvent.value = { kind: turnFailed ? 'fail' : 'win', at: Date.now() }
  const next = queue.value.shift()
  if (next !== undefined) void startTurn(next)
}

// ---------------------------------------------------------------- 一轮对话
async function startTurn(text: string) {
  msgs.value.push({ kind: 'user', text })
  beginTurn(text, '研究中')
  // 预定义工作流优先（无 AI Key 也可用），未命中再走 Agent 流式对话
  try {
    const route = await agentRoute(text)
    if (route.matched) {
      busyLabel.value = '执行工作流'
      const at = Date.now()
      for (const step of route.steps ?? []) {
        const t: ToolCall = {
          id: `t${++uid}`,
          turn: turnNo,
          name: step.tool || step.name,
          args: step.tool && step.name !== step.tool ? { step: step.name } : {},
          status: step.success ? 'done' : 'failed',
          start: at,
          end: at,
          result: step.success ? '完成' : '失败',
        }
        if (!step.success) turnFailed = true
        tools.value.push(t)
        msgs.value.push({ kind: 'tool', id: t.id })
      }
      msgs.value.push({ kind: 'text', text: route.reply || '工作流执行完成。' })
      endTurn()
      return
    }
  } catch {
    // 路由失败不阻塞：直接交给 Agent
  }
  void agent.send(text, sessionId.value)
}

function interrupt() {
  if (!busy.value) return
  agent.cancel()
  turnInterrupted = true
  const at = Date.now()
  for (const t of tools.value) {
    if (t.status === 'running') {
      t.status = 'cancelled'
      t.end = at
      t.result = '已被用户中断'
    }
  }
  for (const m of msgs.value) if (m.kind === 'confirm' && !m.decision) m.decision = 'cancelled'
  mascotEvent.value = { kind: 'stop', at }
  msgs.value.push({ kind: 'sys', text: '⎿ 已中断，可继续输入新的指令', tone: 'dim' })
}

function decide(m: Extract<Msg, { kind: 'confirm' }>, d: Decision) {
  if (m.decision) return
  m.decision = d
  agent.confirm(m.id, d)
  focusInput()
}

const pendingConfirm = computed(() =>
  [...msgs.value].reverse().find((m): m is Extract<Msg, { kind: 'confirm' }> => m.kind === 'confirm' && !m.decision),
)

// ---------------------------------------------------------------- 命令
function sys(text: string, tone?: 'dim' | 'warn' | 'fail') {
  msgs.value.push({ kind: 'sys', text, tone })
}

function clearAll() {
  msgs.value = []
  tools.value = []
  for (const k of Object.keys(turns)) delete turns[Number(k)]
  selTool.value = null
}

async function loadHistory(note: string) {
  try {
    const items = await historyMessages(40)
    if (items.length) {
      msgs.value.push(...items)
      sys(`↩ ${note} · ${items.length} 条（/new 开新对话 · /resume 切换）`, 'dim')
    }
  } catch {
    /* 历史读取失败不影响使用 */
  }
}

async function runCommand(text: string) {
  const [cmd, ...args] = text.split(/\s+/)
  const known = COMMANDS.some((c) => c.cmd === cmd)
  if (!known) {
    msgs.value.push({ kind: 'user', text })
    sys(`未知命令 ${cmd}，输入 /help 查看全部命令`, 'warn')
    return
  }
  if (cmd === '/clear') return clearAll()
  msgs.value.push({ kind: 'user', text })
  switch (cmd) {
    case '/help':
      return sys(helpText())
    case '/tools':
      showTimeline.value = !showTimeline.value
      return sys(showTimeline.value ? '已显示工具调用时间线' : '已隐藏工具调用时间线')
    case '/theme': {
      const name = args[0] ?? ''
      if (!isTheme(name)) return sys(themeList(theme.value, name || undefined))
      theme.value = name
      return sys(`已切换主题 → ${THEME_LABELS[name]}`)
    }
    case '/new':
      if (busy.value) interrupt()
      sessionId.value = resetChatSessionId()
      clearAll()
      return sys(`已开新会话 ${sessionId.value}（旧会话保留在 /resume 列表）`, 'dim')
    case '/resume':
      if (args[0]) {
        if (busy.value) interrupt()
        setChatSessionId(args[0])
        sessionId.value = args[0]
        clearAll()
        return loadHistory(`已切换到会话 ${args[0]}`)
      }
  }
  busy.value = true
  busyLabel.value = '读取数据'
  busyStart.value = Date.now()
  try {
    const out = await runDataCommand(cmd, args)
    if (out) msgs.value.push(...out)
  } catch (e) {
    const err = toApiError(e, cmd)
    // 503 = 后台行情快照还没生成（刚启动的首次轮询），这是正常冷启动，不是故障
    if (err.status === 503) sys('行情数据还在准备中（服务刚启动，首次拉取行情），稍等几秒再试', 'warn')
    else sys(`✗ ${err.friendly}`, 'fail')
  } finally {
    busy.value = false
  }
}

function submit(raw: string) {
  const text = raw.trim()
  input.value = ''
  sel.value = 0
  menuDismissed.value = false
  if (!text) return
  lastActive = Date.now()
  if (auth.value === 'pairing') return void pair(text)
  if (text.startsWith('/')) return void runCommand(text)
  sent.push(text)
  histIdx = -1
  if (isStockCode(text) && /^\d{6}$/.test(text)) return void runCommand(`/quote ${text}`)
  if (busy.value) {
    queue.value.push(text)
    return
  }
  void startTurn(text)
}

// ---------------------------------------------------------------- 菜单（/ 命令 · @ 股票）
const atToken = computed(() => /@([^\s@]+)$/.exec(input.value)?.[1] ?? '')
const slashList = computed(() => filterCommands(input.value))
const menuMode = computed<'slash' | 'stock' | null>(() => {
  if (menuDismissed.value) return null
  if (input.value.startsWith('/') && !input.value.includes(' ')) return 'slash'
  if (atToken.value && stockHits.value.length) return 'stock'
  return null
})
const menuCount = computed(() => (menuMode.value === 'slash' ? slashList.value.length : stockHits.value.length))

let searchTimer = 0
watch(atToken, (q) => {
  window.clearTimeout(searchTimer)
  if (!q) {
    stockHits.value = []
    return
  }
  searchTimer = window.setTimeout(async () => {
    try {
      stockHits.value = (await searchStocks(q, 8)).slice(0, 8)
      sel.value = 0
    } catch {
      stockHits.value = []
    }
  }, 180)
})

function pickCommand(c: Command) {
  if (c.needs) {
    input.value = `${c.cmd} `
    menuDismissed.value = false
    focusInput()
  } else submit(c.cmd)
}

function pickStock(h: StockSearchResult) {
  input.value = input.value.replace(/@([^\s@]+)$/, `${h.name}(${h.code}) `)
  stockHits.value = []
  focusInput()
}

function onInput(e: Event) {
  input.value = (e.target as HTMLInputElement).value
  sel.value = 0
  menuDismissed.value = false
  lastActive = Date.now()
}

function onKey(e: KeyboardEvent) {
  const open = menuMode.value !== null && menuCount.value > 0
  const confirmReq = pendingConfirm.value
  if (confirmReq && !input.value && ['y', 'n', 'a'].includes(e.key)) {
    e.preventDefault()
    decide(confirmReq, ({ y: 'allow', n: 'deny', a: 'always' } as const)[e.key as 'y' | 'n' | 'a'])
    return
  }
  if (e.key === 'Escape') {
    e.preventDefault()
    if (open) menuDismissed.value = true
    else if (busy.value) interrupt()
    return
  }
  if (open && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
    e.preventDefault()
    const n = menuCount.value
    sel.value = (sel.value + (e.key === 'ArrowDown' ? 1 : n - 1)) % n
    return
  }
  if (open && e.key === 'Tab') {
    e.preventDefault()
    if (menuMode.value === 'slash') {
      const c = slashList.value[Math.min(sel.value, slashList.value.length - 1)]
      input.value = c.cmd + (c.arg ? ' ' : '')
    } else pickStock(stockHits.value[Math.min(sel.value, stockHits.value.length - 1)])
    return
  }
  if (e.key === 'Enter') {
    e.preventDefault()
    if (open && menuMode.value === 'slash') return pickCommand(slashList.value[Math.min(sel.value, slashList.value.length - 1)])
    if (open && menuMode.value === 'stock') return pickStock(stockHits.value[Math.min(sel.value, stockHits.value.length - 1)])
    return submit(input.value)
  }
  if (!open && (e.key === 'ArrowUp' || e.key === 'ArrowDown') && sent.length) {
    e.preventDefault()
    if (e.key === 'ArrowUp') histIdx = histIdx === -1 ? sent.length - 1 : Math.max(0, histIdx - 1)
    else histIdx = histIdx === -1 || histIdx >= sent.length - 1 ? -1 : histIdx + 1
    input.value = histIdx === -1 ? '' : sent[histIdx]
  }
}

function focusInput() {
  if (!window.getSelection()?.toString()) inputEl.value?.focus()
}

// ---------------------------------------------------------------- 渲染辅助
const toolMap = computed(() => Object.fromEntries(tools.value.map((t) => [t.id, t])))

function toolLine(id: string) {
  const t = toolMap.value[id]
  if (!t) return null
  const elapsed = t.start ? fmtDur((t.end ?? now.value) - t.start) : ''
  const look = {
    queued: { color: 'var(--dim)', res: '等待前序步骤完成', resColor: 'var(--dim)' },
    running: { color: 'var(--run)', res: `运行中… ${elapsed}`, resColor: 'var(--run)' },
    done: { color: 'var(--accent)', res: `${digest(t.result) || '完成'} · ${elapsed}`, resColor: 'var(--muted)' },
    failed: { color: 'var(--fail)', res: `${digest(t.result) || '失败'} · ${elapsed}`, resColor: 'var(--fail)' },
    cancelled: { color: 'var(--faint)', res: '已被用户中断', resColor: 'var(--faint)' },
    denied: { color: 'var(--run)', res: '已拒绝（用户）', resColor: 'var(--run)' },
  }[t.status]
  return { name: t.name, args: argStr(t.args), ...look }
}

marked.setOptions({ gfm: true, breaks: true })
function md(text: string): string {
  return DOMPurify.sanitize(marked.parse(text, { async: false }) as string)
}

function toneOf(m: Extract<Msg, { kind: 'table' }>, r: number, c: number, v: string): string {
  const explicit = m.tones?.[r]?.[c]
  if (explicit !== undefined) return explicit
  const t = cellTone(v)
  return t === 'up' ? 'rise' : t === 'down' ? 'fall' : ''
}

const spin = computed(() => SPIN[tick.value % SPIN.length])
const busyElapsed = computed(() => ((now.value - busyStart.value) / 1000).toFixed(1))

const running = computed(() => tools.value.filter((t) => t.status === 'running'))
const mascot = computed(() => {
  const ev = mascotEvent.value
  return mascotView({
    busy: busy.value,
    busyLabel: busyLabel.value,
    running: running.value.map((t) => t.name),
    runningMs: running.value.length ? now.value - Math.min(...running.value.map((t) => t.start ?? now.value)) : 0,
    event: ev ? { kind: ev.kind, ageMs: now.value - ev.at } : null,
    idleMs: now.value - lastActive,
    pokeAgeMs: now.value - poked,
    awaitingConfirm: !!pendingConfirm.value,
  })
})

function poke() {
  poked = Date.now()
  lastActive = poked
}

const panelVisible = computed(() => showTimeline.value)
const placeholder = computed(() =>
  auth.value === 'pairing'
    ? '输入配对码（运行 mommy-web 的终端里会打印），回车提交'
    : '提问，或输入 / 查看命令（例：/quote 600519 · 分析一下 @茅台）',
)

// ---------------------------------------------------------------- 生命周期
watch(theme, (t) => {
  document.documentElement.dataset.theme = t
  saveTheme(t)
}, { immediate: true })

watch(
  () => [msgs.value.length, busy.value, (msgs.value[msgs.value.length - 1] as { text?: string } | undefined)?.text?.length],
  () => nextTick(() => scrollEl.value && (scrollEl.value.scrollTop = scrollEl.value.scrollHeight)),
)

async function bootstrap() {
  try {
    const status = await loadAuthStatus()
    if (!status.authenticated && status.mode !== 'none') {
      auth.value = 'pairing'
      return
    }
    auth.value = 'ok'
    llmConfigured.value = status.llm_configured !== false
  } catch {
    auth.value = 'offline'
    return
  }
  const [info, h] = await Promise.all([getAgentInfo().catch(() => null), health().catch(() => null)])
  if (info?.configured) modelLabel.value = info.model || info.provider
  dataSource.value = h?.adapter_name ? prettySource(h.adapter_name) : ''
  await loadHistory('已恢复本会话')
}

async function pair(code: string) {
  try {
    const res = await submitPairingCode(code)
    if (!res.ok) return sys(`✗ ${res.message || '配对码无效'}`, 'fail')
    sys('✓ 配对成功', 'dim')
    await bootstrap()
  } catch (e) {
    sys(`✗ ${toApiError(e, '配对').friendly}`, 'fail')
  }
}

let spinTimer = 0
let clockTimer = 0
const mq = window.matchMedia('(max-width: 900px)')
const onMq = () => {
  narrow.value = mq.matches
  if (mq.matches) showTimeline.value = false
}

onMounted(() => {
  onMq()
  mq.addEventListener('change', onMq)
  spinTimer = window.setInterval(() => {
    if (busy.value) tick.value += 1
  }, 100)
  clockTimer = window.setInterval(() => {
    now.value = Date.now()
  }, 100)
  focusInput()
  void bootstrap()
})

onBeforeUnmount(() => {
  window.clearInterval(spinTimer)
  window.clearInterval(clockTimer)
  mq.removeEventListener('change', onMq)
  agent.close()
})
</script>

<template>
  <div class="app">
    <header class="topbar">
      <div class="dots"><span></span><span></span><span></span></div>
      <div class="brand">
        <img src="/mascot/logo_face.png" alt="" class="logo" />
        <div class="wordmark">
          <div class="wm-row">
            <span class="wm">妈咪炒股</span>
            <svg width="11" height="11" viewBox="0 0 12 12" class="wm-arrow">
              <path d="M2 10 L9.5 2.5 M4.5 2 H10 V7.5" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </div>
          <span class="tagline">AI 投研 Agent</span>
        </div>
      </div>
      <span class="hide-narrow" :title="sessionId">会话 {{ shortSession(sessionId) }}</span>
      <span class="grow"></span>
      <span v-if="modelLabel" class="hide-narrow">模型 {{ modelLabel }}</span>
      <span v-if="dataSource" class="hide-narrow">数据源 {{ dataSource }}</span>
    </header>

    <div class="main">
      <section class="chat" @click="focusInput">
        <div ref="scrollEl" class="log" data-testid="chat-log">
          <div class="welcome">
            <div><span class="accent">✻</span> 欢迎使用 <b>妈咪炒股 · AI 投研 Agent</b></div>
            <div class="dim">Better Research · Smarter Decisions · Happier Life</div>
            <div class="dim gap">
              输入 <span class="text">/</span> 打开命令菜单 · 直接提问开始研究 · <span class="text">@</span> 联想股票 ·
              <span class="text">esc</span> 中断当前任务
            </div>
            <div v-if="auth === 'pairing'" class="warn">远程访问需要配对：在下方输入配对码</div>
            <div v-else-if="auth === 'offline'" class="fail">无法连接本地服务，请确认 mommy-web 正在运行后刷新</div>
            <div v-else-if="!llmConfigured" class="warn">AI 未配置：行情命令与预定义工作流可用；在终端运行 mommy setup 后刷新即可对话</div>
          </div>

          <div v-for="(m, i) in msgs" :key="i" class="msg">
            <div v-if="m.kind === 'user'" class="user"><span class="dim">›</span><span class="pre">{{ m.text }}</span></div>

            <div v-else-if="m.kind === 'text'" class="answer">
              <span>⏺</span>
              <div class="md" v-html="md(m.text + (m.interrupted ? '\n\n*（已中断）*' : ''))"></div>
            </div>

            <div v-else-if="m.kind === 'sys'" class="sys" :class="m.tone">{{ m.text }}</div>

            <div v-else-if="m.kind === 'tool' && toolLine(m.id)" class="tool">
              <div class="row">
                <span :style="{ color: toolLine(m.id)!.color }">⏺</span>
                <span><b>{{ toolLine(m.id)!.name }}</b><span class="dim">({{ toolLine(m.id)!.args }})</span></span>
              </div>
              <div class="res dim">
                <span>⎿</span><span :style="{ color: toolLine(m.id)!.resColor }">{{ toolLine(m.id)!.res }}</span>
              </div>
            </div>

            <div v-else-if="m.kind === 'table'" class="table-wrap">
              <table class="grid">
                <thead>
                  <tr><th v-for="(h, c) in m.header" :key="c" :class="{ num: c > 0 }">{{ h }}</th></tr>
                </thead>
                <tbody>
                  <tr v-for="(r, ri) in m.rows" :key="ri">
                    <td v-for="(v, c) in r" :key="c" :class="[{ num: c > 0 }, toneOf(m, ri, c, v)]">{{ v }}</td>
                  </tr>
                </tbody>
              </table>
              <div v-if="m.note" class="note dim">{{ m.note }}</div>
            </div>

            <div v-else-if="m.kind === 'thinking'" class="thinking">
              <div class="th-head" @click.stop="m.open = !m.open">
                <span class="accent">✻</span>
                {{ m.done ? `思考完成 · ${m.text.length} 字 · ${fmtDur(m.ms ?? 0)}` : '思考中…' }}
                <span class="dim">（{{ m.open ? '收起' : '展开' }}）</span>
              </div>
              <div v-if="m.open || !m.done" class="th-body pre">{{ m.done ? m.text : m.text.slice(-240) }}</div>
            </div>

            <div v-else-if="m.kind === 'confirm'" class="confirm" :class="{ pending: !m.decision }" data-testid="confirm">
              <div>
                <span class="run">需要确认写操作</span>&nbsp; <b>{{ m.description }}</b>
              </div>
              <div class="dim small">{{ m.tool }}({{ argStr(m.args) }})</div>
              <div v-if="!m.decision" class="actions">
                <button class="btn primary" @click.stop="decide(m, 'allow')">允许 y</button>
                <button class="btn" @click.stop="decide(m, 'deny')">拒绝 n</button>
                <button class="btn" @click.stop="decide(m, 'always')">本会话不再询问 a</button>
              </div>
              <div v-else class="dim small">
                ⎿ {{ { allow: '已允许', always: '已允许（本会话不再询问）', deny: '已拒绝', cancelled: '已取消（本轮中断）' }[m.decision] }}
              </div>
            </div>
          </div>

          <div v-if="busy" class="busy">
            <span>{{ spin }}</span>
            <span>
              {{ retryNote || `${busyLabel}…` }}
              <span class="dim">({{ busyElapsed }}s · esc 中断{{ queue.length ? ` · 已排队 ${queue.length} 条` : '' }})</span>
            </span>
          </div>
        </div>

        <div class="composer">
          <div v-if="menuMode" class="menu" data-testid="menu">
            <template v-if="menuMode === 'slash'">
              <div
                v-for="(c, i) in slashList"
                :key="c.cmd"
                class="item"
                :class="{ sel: i === Math.min(sel, slashList.length - 1) }"
                @click.stop="pickCommand(c)"
                @mouseenter="sel = i"
              >
                <b>{{ c.cmd }}</b>
                <span class="dim ellipsis">{{ c.arg }}</span>
                <span class="ellipsis">{{ c.desc }}</span>
              </div>
              <div v-if="!slashList.length" class="item-empty dim">没有匹配的命令</div>
            </template>
            <template v-else>
              <div
                v-for="(h, i) in stockHits"
                :key="h.code"
                class="item"
                :class="{ sel: i === Math.min(sel, stockHits.length - 1) }"
                @click.stop="pickStock(h)"
                @mouseenter="sel = i"
              >
                <b>{{ h.name }}</b>
                <span class="dim">{{ h.code }}</span>
                <span class="dim">{{ { watchlist: '自选', semicon: '半导体库', cache: '近期查过', remote: '全网' }[h.source] }}</span>
              </div>
            </template>
            <div class="menu-foot">↑↓ 选择 · tab 补全 · enter 执行 · esc 关闭</div>
          </div>
          <div class="input-box">
            <span class="accent">›</span>
            <input
              ref="inputEl"
              :value="input"
              :placeholder="placeholder"
              spellcheck="false"
              autocomplete="off"
              data-testid="prompt"
              @input="onInput"
              @keydown="onKey"
            />
          </div>
        </div>
        <footer class="statusbar">
          <span class="dim-strong">⏵⏵ 只读工具自动执行</span>
          <span>/ 命令</span>
          <span>@ 股票</span>
          <span>esc 中断</span>
          <span v-if="pendingConfirm" class="run">y 允许 · n 拒绝 · a 本会话不再询问</span>
          <span class="grow"></span>
          <span>{{ thousands(tokens) }} tokens</span>
        </footer>
      </section>

      <aside v-if="panelVisible" class="panel" :class="{ overlay: narrow }" :style="{ width: narrow ? undefined : `${PANEL_W}px` }">
        <MascotPanel :view="mascot" :busy="busy" @poke="poke" />
        <ToolTimeline
          :tools="tools"
          :turns="turns"
          :now="now"
          :spin="spin"
          :selected="selTool"
          @select="(id) => (selTool = selTool === id ? null : id)"
          @hide="showTimeline = false"
        />
      </aside>
    </div>
  </div>
</template>

<style scoped>
.app {
  height: 100vh;
  height: 100dvh;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  color: var(--text);
  font-family: 'JetBrains Mono', 'Noto Sans SC', ui-monospace, 'SFMono-Regular', Menlo, 'PingFang SC', 'Microsoft YaHei', monospace;
  font-size: 13px;
  line-height: 1.6;
}
.topbar {
  display: flex; align-items: center; gap: 16px; padding: 6px 14px;
  border-bottom: 1px solid var(--line); background: var(--bg2); color: var(--dim); font-size: 12px; flex-shrink: 0;
}
.dots { display: flex; gap: 6px; }
.dots span { width: 10px; height: 10px; border-radius: 50%; background: var(--dots); }
.brand { display: flex; align-items: center; gap: 8px; margin-left: 4px; }
.logo { height: 30px; width: auto; display: block; }
.wordmark { display: flex; flex-direction: column; line-height: 1; gap: 3px; }
.wm-row { display: flex; align-items: flex-start; gap: 1px; }
.wm { font-family: 'Noto Sans SC', 'PingFang SC', sans-serif; font-weight: 900; font-size: 17px; letter-spacing: 0.5px; color: var(--text); transform: skewX(-6deg); display: inline-block; }
.wm-arrow { color: var(--accent); margin-top: -2px; }
.tagline { font-family: 'Noto Sans SC', 'PingFang SC', sans-serif; font-weight: 700; font-size: 9.5px; letter-spacing: 1px; color: var(--dim); transform: skewX(-6deg); display: inline-block; }
.grow { flex: 1; }
.main { flex: 1; display: flex; min-height: 0; position: relative; }
.chat { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.log { flex: 1; overflow-y: auto; padding: 16px 20px 8px; }
.welcome { border: 1px solid var(--accent); border-radius: 4px; padding: 10px 14px; margin-bottom: 18px; max-width: 640px; }
.welcome .gap { margin-top: 4px; }
.accent { color: var(--accent); }
.dim { color: var(--dim); }
.text { color: var(--text); }
.run { color: var(--run); }
.warn { color: var(--run); }
.fail { color: var(--fail); }
.small { font-size: 12px; }
.pre { white-space: pre-wrap; }
.ellipsis { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.msg { margin-bottom: 12px; }
.user { display: flex; gap: 10px; background: var(--userbg); padding: 4px 10px; border-left: 2px solid var(--strong); color: var(--usertext); }
.answer { display: flex; gap: 10px; }
.sys { white-space: pre; color: var(--muted); padding-left: 20px; overflow-x: auto; }
.sys.dim { color: var(--dim); }
.sys.warn { color: var(--run); }
.sys.fail { color: var(--fail); }
.tool .row { display: flex; gap: 10px; }
.tool .res { display: flex; gap: 8px; padding-left: 20px; }
.table-wrap { padding-left: 20px; overflow-x: auto; }
.grid { border-collapse: collapse; border: 1px solid var(--line2); }
.grid th, .grid td { padding: 2px 12px; border-bottom: 1px solid var(--line); white-space: nowrap; text-align: left; }
.grid th { color: var(--dim); font-weight: 500; background: var(--thbg); }
.grid .num { text-align: right; }
.note { margin-top: 4px; font-size: 12px; }
.thinking .th-head { cursor: pointer; color: var(--muted); }
.thinking .th-body { color: var(--dim); padding: 2px 0 0 20px; max-height: 280px; overflow-y: auto; }
.confirm { border: 1px solid var(--strong); border-radius: 4px; padding: 8px 12px; margin-left: 20px; max-width: 640px; }
.confirm.pending { border-color: var(--run); background: var(--thbg); }
.actions { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
.btn { background: transparent; color: var(--text); border: 1px solid var(--strong); border-radius: 4px; padding: 2px 10px; cursor: pointer; }
.btn:hover { background: var(--hover); }
.btn.primary { border-color: var(--accent); color: var(--accent); }
.busy { display: flex; gap: 10px; color: var(--run); }
.composer { position: relative; padding: 4px 20px 0; flex-shrink: 0; }
.menu {
  position: absolute; left: 20px; right: 20px; bottom: 100%; background: var(--menu);
  border: 1px solid var(--line2); border-radius: 4px; padding: 6px 0; max-height: 340px; overflow-y: auto;
  box-shadow: 0 -8px 24px var(--shadow); z-index: 5;
}
.item { display: grid; grid-template-columns: 150px 170px minmax(0, 1fr); gap: 12px; padding: 2px 14px; cursor: pointer; color: var(--text); }
.item.sel { background: var(--sel); color: var(--accent); }
.item-empty { padding: 2px 14px; }
.menu-foot { padding: 6px 14px 0; margin-top: 4px; border-top: 1px solid var(--line); color: var(--faint); font-size: 12px; }
.input-box { display: flex; align-items: center; gap: 10px; border: 1px solid var(--strong); border-radius: 4px; padding: 8px 12px; }
.input-box input { flex: 1; min-width: 0; background: transparent; border: none; outline: none; color: var(--text); font: inherit; caret-color: var(--accent); }
.statusbar { display: flex; gap: 16px; padding: 4px 22px 8px; color: var(--faint); font-size: 12px; flex-shrink: 0; flex-wrap: wrap; }
.dim-strong { color: var(--dim); }
.panel { flex-shrink: 0; border-left: 1px solid var(--line); background: var(--bg2); display: flex; flex-direction: column; min-height: 0; }
.panel.overlay { position: absolute; inset: 0 0 0 auto; width: min(420px, 100%); z-index: 10; box-shadow: -8px 0 24px var(--shadow); }
@media (max-width: 900px) {
  .hide-narrow { display: none; }
  .log { padding: 12px; }
  .composer { padding: 4px 12px 0; }
  .menu { left: 12px; right: 12px; }
  .item { grid-template-columns: 110px minmax(0, 1fr); }
  .item > :nth-child(2) { display: none; }
  .statusbar { padding: 4px 14px 8px; gap: 10px; }
}
</style>

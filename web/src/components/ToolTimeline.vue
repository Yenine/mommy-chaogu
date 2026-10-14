<script setup lang="ts">
// 工具调用时间线（设计稿右栏）：按轮次分组，状态 / 耗时 / 参数 / 本轮内起止进度条，点击展开详情。
import { computed } from 'vue'
import { argStr, argsJson, clock, fmtDur } from '@/lib/format'
import type { ToolCall, ToolStatus, TurnInfo } from '@/lib/messages'

const props = defineProps<{
  tools: ToolCall[]
  turns: Record<number, TurnInfo>
  now: number
  spin: string
  selected: string | null
}>()
const emit = defineEmits<{ select: [id: string]; hide: [] }>()

interface Look { color: string; icon?: string; label: string; res: string; resColor: string }

const looks: Record<ToolStatus, Look> = {
  queued: { color: 'var(--dim)', icon: '○', label: '排队中', res: '等待前序步骤完成', resColor: 'var(--dim)' },
  running: { color: 'var(--run)', label: '运行中', res: '运行中…', resColor: 'var(--run)' },
  done: { color: 'var(--accent)', icon: '✓', label: '完成', res: '', resColor: 'var(--muted)' },
  failed: { color: 'var(--fail)', icon: '✗', label: '失败', res: '', resColor: 'var(--fail)' },
  cancelled: { color: 'var(--faint)', icon: '⊘', label: '已中断', res: '已被用户中断', resColor: 'var(--faint)' },
  denied: { color: 'var(--run)', icon: '⊘', label: '已拒绝', res: '已拒绝（用户）', resColor: 'var(--run)' },
}

const stat = computed(() => {
  const cnt = (s: ToolStatus) => props.tools.filter((t) => t.status === s).length
  return {
    total: props.tools.length,
    done: cnt('done'),
    running: cnt('running'),
    queued: cnt('queued'),
    failed: cnt('failed'),
  }
})

const rows = computed(() => {
  const span: Record<number, { a: number; b: number }> = {}
  for (const t of props.tools) {
    const sp = span[t.turn] ?? (span[t.turn] = { a: Infinity, b: 0 })
    if (t.start) {
      sp.a = Math.min(sp.a, t.start)
      sp.b = Math.max(sp.b, t.end ?? props.now)
    }
  }
  let lastTurn: number | null = null
  return props.tools.map((t) => {
    const L = looks[t.status]
    const first = t.turn !== lastTurn
    lastTurn = t.turn
    const sp = span[t.turn]
    const total = Math.max(sp.b - sp.a, 1)
    const end = t.end ?? props.now
    const left = t.start ? ((t.start - sp.a) / total) * 100 : 0
    const width = t.start ? Math.max(((end - t.start) / total) * 100, 1.5) : 0
    const tr = props.turns[t.turn]
    return {
      t,
      first,
      turnLabel: tr?.label ?? '',
      turnClock: tr ? clock(tr.start) : '',
      color: L.color,
      icon: t.status === 'running' ? props.spin : (L.icon ?? ''),
      label: L.label,
      res: t.status === 'running' ? '运行中…' : L.res || t.result || '—',
      resColor: L.resColor,
      dur: t.start ? fmtDur(end - t.start) : '—',
      startClock: t.start ? clock(t.start) : '未开始',
      args: argStr(t.args),
      argsJson: argsJson(t.args),
      left: `${left}%`,
      width: `${width}%`,
      open: props.selected === t.id,
    }
  })
})
</script>

<template>
  <div class="head">
    <div class="title-row">
      <span class="title">工具调用时间线</span>
      <span class="grow"></span>
      <span class="close" title="隐藏（/tools 再打开）" @click="emit('hide')">✕</span>
    </div>
    <div class="stats" data-testid="timeline-stats">
      <span>共 <b>{{ stat.total }}</b></span>
      <span><i style="color: var(--accent)">✓</i> {{ stat.done }}</span>
      <span><i style="color: var(--run)">●</i> {{ stat.running }}</span>
      <span><i style="color: var(--dim)">○</i> {{ stat.queued }}</span>
      <span><i style="color: var(--fail)">✗</i> {{ stat.failed }}</span>
    </div>
  </div>
  <div class="list">
    <div v-for="r in rows" :key="r.t.id" data-testid="timeline-row">
      <div v-if="r.first" class="turn">
        <span style="color: var(--blue)">#{{ r.t.turn }}</span>
        <span class="ellipsis grow">{{ r.turnLabel }}</span>
        <span>{{ r.turnClock }}</span>
      </div>
      <div class="row" :class="{ open: r.open }" @click="emit('select', r.t.id)">
        <div class="rail">
          <span :style="{ color: r.color }" class="icon">{{ r.icon }}</span>
          <span class="line"></span>
        </div>
        <div class="body">
          <div class="name-row">
            <span class="name ellipsis">{{ r.t.name }}</span>
            <span class="grow"></span>
            <span class="status" :style="{ color: r.color }">{{ r.label }}</span>
            <span class="dur">{{ r.dur }}</span>
          </div>
          <div class="args ellipsis">{{ r.args }}</div>
          <div class="track">
            <div class="fill" :style="{ left: r.left, width: r.width, background: r.color }"></div>
          </div>
          <div v-if="r.open" class="detail">
            <span class="k">开始</span><span>{{ r.startClock }}</span>
            <span class="k">耗时</span><span>{{ r.dur }}</span>
            <span class="k">参数</span><span class="json">{{ r.argsJson }}</span>
            <span class="k">结果</span><span class="res" :style="{ color: r.resColor }">{{ r.res }}</span>
          </div>
        </div>
      </div>
    </div>
    <div v-if="!tools.length" class="empty">暂无工具调用</div>
  </div>
</template>

<style scoped>
.head { padding: 10px 16px; border-bottom: 1px solid var(--line); flex-shrink: 0; }
.title-row { display: flex; align-items: center; gap: 8px; }
.title { font-weight: 700; }
.grow { flex: 1; }
.close { color: var(--faint); cursor: pointer; }
.close:hover { color: var(--text); }
.stats { display: flex; gap: 14px; margin-top: 6px; font-size: 12px; color: var(--dim); }
.stats b { color: var(--text); font-weight: 400; }
.stats i { font-style: normal; }
.list { flex: 1; overflow-y: auto; padding: 8px 0 16px; }
.turn { display: flex; gap: 8px; padding: 12px 16px 6px; font-size: 12px; color: var(--dim); }
.ellipsis { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.row { display: grid; grid-template-columns: 18px minmax(0, 1fr); gap: 8px; padding: 4px 16px; cursor: pointer; }
.row:hover, .row.open { background: var(--hover); }
.rail { display: flex; flex-direction: column; align-items: center; }
.icon { line-height: 20px; }
.line { flex: 1; width: 1px; background: var(--line2); min-height: 8px; }
.body { min-width: 0; padding-bottom: 4px; }
.name-row { display: flex; gap: 8px; align-items: baseline; }
.name { font-weight: 700; }
.status { font-size: 11px; white-space: nowrap; }
.dur { font-size: 12px; color: var(--muted); white-space: nowrap; min-width: 44px; text-align: right; }
.args { font-size: 12px; color: var(--dim); }
.track { position: relative; height: 4px; background: var(--track); margin-top: 5px; }
.fill { position: absolute; top: 0; bottom: 0; opacity: 0.85; }
.detail { margin-top: 8px; font-size: 12px; border: 1px solid var(--line2); padding: 6px 10px; background: var(--bg); display: grid; grid-template-columns: 44px minmax(0, 1fr); gap: 2px 10px; }
.k { color: var(--dim); }
.json { white-space: pre-wrap; word-break: break-all; color: var(--blue); }
.res { white-space: pre-wrap; word-break: break-word; max-height: 240px; overflow-y: auto; }
.empty { padding: 16px; color: var(--faint); }
</style>

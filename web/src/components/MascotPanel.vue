<script setup lang="ts">
// 妈咪：立绘 + 气泡 + 状态行；动画逐帧照搬设计稿（呼吸起伏、换姿势弹一下、完成时跳起来）。
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ALL_POSES, type MascotView } from '@/lib/mascot'

const props = defineProps<{ view: MascotView; busy: boolean }>()
const emit = defineEmits<{ poke: [] }>()

const img = ref<HTMLImageElement | null>(null)
const bubble = ref<HTMLDivElement | null>(null)
const src = (pose: string) => `${import.meta.env.BASE_URL}mascot/${pose}.png`

let raf = 0
let pk = 1, pv = 0, bk = 1, bv = 0, jump0 = -1e9

watch(
  () => [props.view.pose, props.view.say] as const,
  ([pose], [prevPose]) => {
    if (pose !== prevPose) {
      pk = 0.84
      pv = 0
      if (pose === 'p_win' || pose === 'p_up') jump0 = performance.now()
    }
    bk = 0.7
    bv = 0
  },
)

function poke() {
  jump0 = performance.now()
  emit('poke')
}

onMounted(() => {
  for (const p of ALL_POSES) new Image().src = src(p)
  const loop = (now: number) => {
    raf = requestAnimationFrame(loop)
    const t = now / 1000
    const k = props.view.pose
    const sleepy = k === 'e_sleep' || k === 'p_coffee' || k === 'p_wait'
    pv = (pv + (1 - pk) * 0.2) * 0.74
    pk += pv
    bv = (bv + (1 - bk) * 0.22) * 0.72
    bk += bv
    const jp = (now - jump0) / 420
    const jy = jp >= 0 && jp < 1 ? -22 * 4 * jp * (1 - jp) : 0
    const sp = sleepy ? 1.3 : props.busy ? 3.2 : 2.2
    const amp = sleepy ? 1.5 : props.busy ? 3 : 2.5
    const y = Math.sin(t * sp) * amp + jy
    const br = Math.sin(t * sp + 1.2) * 0.012
    if (img.value) {
      img.value.style.transform = `translateY(${y}px) rotate(${Math.sin(t * 1.1) * (props.busy ? 1.6 : 1)}deg) scale(${pk * (1 - br)}, ${pk * (1 + br)})`
    }
    if (bubble.value) bubble.value.style.transform = `translateY(${Math.sin(t * 2 + 1) * 1.5}px) scale(${bk})`
  }
  raf = requestAnimationFrame(loop)
})
onBeforeUnmount(() => cancelAnimationFrame(raf))

const dot: Record<MascotView['tone'], string> = {
  accent: 'var(--accent)',
  run: 'var(--run)',
  fail: 'var(--fail)',
  dim: 'var(--dim)',
  cancel: 'var(--faint)',
}
</script>

<template>
  <div class="mascot">
    <div class="figure" title="点我一下" @click="poke">
      <img ref="img" :src="src(view.pose)" alt="妈咪" />
    </div>
    <div class="side">
      <div ref="bubble" class="bubble" data-testid="mascot-say">{{ view.say }}</div>
      <div class="sub">
        <span class="dot" :style="{ background: dot[view.tone] }"></span>
        <span class="ellipsis">{{ view.sub }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mascot { display: flex; align-items: flex-end; gap: 12px; padding: 12px 16px 10px; border-bottom: 1px solid var(--line); flex-shrink: 0; }
.figure { width: 104px; height: 96px; flex-shrink: 0; display: flex; align-items: flex-end; justify-content: center; cursor: pointer; }
.figure img { display: block; max-width: 104px; max-height: 96px; width: auto; height: auto; transform-origin: 50% 100%; will-change: transform; }
.side { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px; padding-bottom: 6px; }
.bubble { align-self: flex-start; max-width: 100%; background: var(--menu); border: 1px solid var(--strong); border-radius: 12px 12px 12px 3px; padding: 5px 11px; font-weight: 700; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; transform-origin: 0% 100%; }
.sub { display: flex; gap: 8px; align-items: center; font-size: 12px; color: var(--dim); min-width: 0; }
.dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.ellipsis { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>

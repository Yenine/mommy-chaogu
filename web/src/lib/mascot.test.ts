import { describe, expect, it } from 'vitest'
import { mascotView, type MascotInput } from './mascot'

const base: MascotInput = { busy: false, busyLabel: '研究中', running: [], runningMs: 0, event: null, idleMs: 0, pokeAgeMs: 1e9 }

describe('妈咪状态机（设计稿规则）', () => {
  it('空闲就绪 → hero', () => {
    expect(mascotView(base)).toMatchObject({ pose: 'hero', say: '嗨～我是妈咪！' })
  })

  it('按工具选姿势，并行时 ×N', () => {
    const v = mascotView({ ...base, busy: true, running: ['search_news', 'get_quote'], runningMs: 1250 })
    expect(v).toMatchObject({ pose: 'p_up', say: '冲！ ×2', tone: 'run' })
    expect(v.sub).toBe('search_news · get_quote · 1.3s')
    expect(mascotView({ ...base, busy: true, running: ['search_news'] }).pose).toBe('p_news')
    expect(mascotView({ ...base, busy: true, running: ['strategy_list'] }).pose).toBe('p_research')
  })

  it('忙碌但没有工具 → 想想', () => {
    expect(mascotView({ ...base, busy: true }).pose).toBe('e_think')
  })

  it('等待写操作确认优先显示', () => {
    expect(mascotView({ ...base, busy: true, running: ['get_quote'], awaitingConfirm: true }).say).toContain('确认')
  })

  it('失败 / 完成 / 中断的短暂反应', () => {
    expect(mascotView({ ...base, busy: true, event: { kind: 'fail', ageMs: 500 } }).pose).toBe('e_huh')
    expect(mascotView({ ...base, event: { kind: 'win', ageMs: 1000 } }).say).toBe('赚到了！')
    expect(mascotView({ ...base, busy: true, event: { kind: 'stop', ageMs: 100 } }).pose).toBe('p_wait')
    expect(mascotView({ ...base, event: { kind: 'win', ageMs: 9000 } }).pose).toBe('hero')
  })

  it('空闲久了喝咖啡、再久睡觉；点一下打招呼', () => {
    expect(mascotView({ ...base, idleMs: 45_000 }).pose).toBe('p_coffee')
    expect(mascotView({ ...base, idleMs: 120_000 }).pose).toBe('e_sleep')
    expect(mascotView({ ...base, pokeAgeMs: 100 }).sub).toContain('试试') // 点一下同时重置空闲计时
  })
})

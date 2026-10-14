import { describe, expect, it } from 'vitest'
import { THEMES, isTheme, themeList } from './themes'

describe('主题', () => {
  it('设计稿 12 套主题', () => {
    // 每套主题的 CSS 变量是否生效由 e2e（真实浏览器）校验
    expect(THEMES).toHaveLength(12)
    expect(new Set(THEMES).size).toBe(12)
  })

  it('/theme 列表按深浅分组并标记当前主题', () => {
    const text = themeList('nord')
    expect(text).toContain('● nord')
    expect(text.indexOf('深色')).toBeLessThan(text.indexOf('浅色'))
    expect(themeList('dark', 'foo')).toMatch(/^未知主题 foo/)
    expect(isTheme('rose-pine-dawn')).toBe(true)
    expect(isTheme('solarized')).toBe(false)
  })
})

// 设计稿 12 套主题（/theme 列表与 html[data-theme] 取值）。

export const THEMES = [
  'dark',
  'light',
  'tokyo-night',
  'catppuccin-mocha',
  'dracula',
  'nord',
  'gruvbox-dark',
  'one-dark',
  'github-light',
  'solarized-light',
  'catppuccin-latte',
  'rose-pine-dawn',
] as const

export type ThemeName = (typeof THEMES)[number]

export const THEME_LABELS: Record<ThemeName, string> = {
  dark: '妈咪 Dark（默认）',
  light: '妈咪 Light · 妈咪紫',
  'tokyo-night': 'Tokyo Night',
  'catppuccin-mocha': 'Catppuccin Mocha',
  dracula: 'Dracula',
  nord: 'Nord',
  'gruvbox-dark': 'Gruvbox Dark',
  'one-dark': 'One Dark',
  'github-light': 'GitHub Light',
  'solarized-light': 'Solarized Light',
  'catppuccin-latte': 'Catppuccin Latte',
  'rose-pine-dawn': 'Rosé Pine Dawn',
}

const DARK: ThemeName[] = ['dark', 'tokyo-night', 'catppuccin-mocha', 'dracula', 'nord', 'gruvbox-dark', 'one-dark']
const LIGHT: ThemeName[] = ['light', 'github-light', 'solarized-light', 'catppuccin-latte', 'rose-pine-dawn']

export function isTheme(name: string): name is ThemeName {
  return (THEMES as readonly string[]).includes(name)
}

/** 不带参数的 /theme：按深浅分组列出，当前主题打 ● */
export function themeList(current: string, unknown?: string): string {
  const row = (n: ThemeName) => `${n === current ? '● ' : '  '}${n.padEnd(18)}${THEME_LABELS[n]}`
  return (
    (unknown ? `未知主题 ${unknown}\n\n` : '') +
    '可用主题（/theme <名称>）\n\n深色  ' +
    DARK.map(row).join('\n      ') +
    '\n\n浅色  ' +
    LIGHT.map(row).join('\n      ')
  )
}

const KEY = 'mommy-theme'

export function loadTheme(): ThemeName {
  try {
    const saved = localStorage.getItem(KEY) ?? ''
    if (isTheme(saved)) return saved
  } catch {
    /* 隐私模式下 localStorage 可能不可用 */
  }
  return 'dark'
}

export function saveTheme(name: ThemeName): void {
  try {
    localStorage.setItem(KEY, name)
  } catch {
    /* ignore */
  }
}

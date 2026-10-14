// 设计稿里的小工具函数（clock / fmtDur / argStr），供对话流与时间线共用。

export const pad = (n: number): string => String(n).padStart(2, '0')

/** 时间戳 → HH:MM:SS（本地时区） */
export function clock(ts: number): string {
  const d = new Date(ts)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** 毫秒 → 850ms / 1.2s */
export function fmtDur(ms: number): string {
  const v = Math.max(0, Math.round(ms))
  return v < 1000 ? `${v}ms` : `${(v / 1000).toFixed(1)}s`
}

/** 工具参数 → `symbol: "300750.SZ", days: 7`（设计稿 argStr） */
export function argStr(args: Record<string, unknown> | undefined | null): string {
  if (!args) return ''
  return Object.entries(args)
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? `[${v.join(', ')}]` : JSON.stringify(v)}`)
    .join(', ')
}

/** 展开详情里的单行 JSON */
export function argsJson(args: Record<string, unknown> | undefined | null): string {
  return JSON.stringify(args ?? {}, null, 1).replace(/\n\s*/g, ' ')
}

/** 表格单元格着色：+ 开头为涨（主色），-数字 为跌（失败色），与设计稿一致 */
export function cellTone(value: string): 'up' | 'down' | '' {
  if (/^\+/.test(value)) return 'up'
  if (/^-\d/.test(value)) return 'down'
  return ''
}

/** 1234 → 1,234 */
export const thousands = (n: number): string => n.toLocaleString('en-US')

/** 结果文本取首行做摘要（时间线 / 对话流 ⎿ 行） */
export function digest(result: string | undefined | null, max = 80): string {
  const line = (result ?? '').split('\n').map((l) => l.trim()).find(Boolean) ?? ''
  return line.length > max ? `${line.slice(0, max - 1)}…` : line
}

/** 数据源标签 → 人话：cached(fallback(massive,yahoo)) → massive · yahoo */
export function prettySource(label: string): string {
  const inner = /\(([^()]+)\)+$/.exec(label)?.[1]
  return inner ? inner.split(',').map((x) => x.trim()).filter(Boolean).join(' · ') : label
}

/** 会话 ID 缩写：web-b301997d-0e20-… → b301997d */
export function shortSession(id: string): string {
  const m = /^web-([0-9a-f]{8})/.exec(id)
  return m ? m[1] : id.length > 16 ? `${id.slice(0, 16)}…` : id
}

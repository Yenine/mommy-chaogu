// 网页版（设计稿单页）浏览器冒烟：真实 mommy-web 提供页面，REST / WebSocket 由 Playwright 模拟，
// 覆盖设计稿的关键交互：/ 菜单、数据命令、工具时间线、写操作确认、esc 中断、主题、配对、窄屏。
import { expect, test, type Page, type WebSocketRoute } from '@playwright/test'

const quote = {
  code: '600519', name: '贵州茅台', market: 'SH', price: '1680.50', change: '30.50', change_pct: '1.85',
  volume: 12_345_678, turnover: '2000000000', open: '1660.00', high: '1690.00', low: '1655.00',
  prev_close: '1650.00', pe: '25.6', pb: '8.1', turnover_rate: '0.98', volume_ratio: '1.23',
  main_net_inflow: '120000000', timestamp: '2026-07-25T15:00:00Z', fetched_at: '2026-07-25T15:00:01Z',
  data_age_seconds: 1,
}

async function mockApi(page: Page, opts: { auth?: 'none' | 'pairing' } = {}) {
  const json = (body: unknown) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  let paired = false
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path === '/api/auth/status') {
      const pairing = opts.auth === 'pairing' && !paired
      return route.fulfill(json({ mode: pairing ? 'pairing' : 'none', authenticated: !pairing, llm_configured: true }))
    }
    if (path === '/api/auth/pair') {
      const body = route.request().postDataJSON() as { code: string }
      paired = body.code === '123456'
      return route.fulfill(json({ ok: paired, message: paired ? 'ok' : '配对码无效' }))
    }
    if (path === '/api/agent/info') return route.fulfill(json({ configured: true, provider: 'deepseek', model: 'deepseek-chat' }))
    if (path === '/api/health') return route.fulfill(json({ ok: true, adapter_name: 'cached(fallback(efinance,tencent))', uptime_seconds: 120, last_snapshot_at: null }))
    if (path === '/api/agent/history') return route.fulfill(json({ messages: [], total: 0 }))
    if (path === '/api/agent/route') return route.fulfill(json({ matched: false }))
    if (path === '/api/agent/sessions') return route.fulfill(json({ sessions: [] }))
    if (path === '/api/quotes/600519') return route.fulfill(json(quote))
    return route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"not mocked"}' })
  })
}

/** 模拟 /ws/agent：收到提问后按协议推送一轮事件；收到的控制消息记录在 sent 里 */
async function mockAgent(page: Page, script: (ws: WebSocketRoute, msg: Record<string, unknown>) => void) {
  const received: Array<Record<string, unknown>> = []
  await page.routeWebSocket(/\/ws\/agent/, (ws) => {
    ws.onMessage((raw) => {
      const msg = JSON.parse(String(raw)) as Record<string, unknown>
      received.push(msg)
      script(ws, msg)
    })
  })
  return received
}

const send = (ws: WebSocketRoute, payload: object) => ws.send(JSON.stringify(payload))

async function ask(page: Page, text: string) {
  const prompt = page.getByTestId('prompt')
  await prompt.click()
  await prompt.fill(text)
  await prompt.press('Enter')
}

test('首屏：品牌、欢迎卡、妈咪、空时间线；顶栏显示模型与数据源', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await mockApi(page)
  await page.goto('/')
  await expect(page.getByText('妈咪炒股', { exact: true })).toBeVisible()
  await expect(page.getByText('欢迎使用')).toBeVisible()
  await expect(page.getByTestId('mascot-say')).toHaveText('嗨～我是妈咪！')
  await expect(page.getByText('暂无工具调用')).toBeVisible()
  await expect(page.getByText('模型 deepseek-chat')).toBeVisible()
  await expect(page.getByText('数据源 efinance · tencent')).toBeVisible()
  await expect(page.getByTestId('prompt')).toBeFocused()
  expect(errors).toEqual([])
})

test('/ 菜单：过滤、↑↓ 选择、Enter 执行；/quote 渲染表格', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  const prompt = page.getByTestId('prompt')
  await prompt.fill('/t')
  await expect(page.getByTestId('menu')).toContainText('/today')
  await expect(page.getByTestId('menu')).toContainText('/theme')
  await prompt.press('Escape')
  await expect(page.getByTestId('menu')).toBeHidden()

  await ask(page, '/quote 600519')
  const log = page.getByTestId('chat-log')
  await expect(log.locator('table')).toContainText('贵州茅台')
  await expect(log.locator('td.rise')).toHaveText('+1.85%')
})

test('/flows：资金流上游失败（503）渲染可见错误行，不渲染 0 值表', async ({ page }) => {
  await mockApi(page)
  // 现契约：上游无数据/请求失败 → HTTP 503（不再返回全 0 的 cumulative）
  await page.route('**/api/quotes/*/money_flow/today', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: '当日资金流不可用（上游无数据或请求失败）' }),
    }),
  )
  await page.goto('/')
  await ask(page, '/flows 600519')
  const log = page.getByTestId('chat-log')
  await expect(log).toContainText('资金流 600519：行情源暂时不可用，稍后重试')
  await expect(log.locator('table')).toHaveCount(0)
  await expect(log).not.toContainText('0.00亿')
})

test('一轮对话：工具进时间线、写操作确认、流式回答、token 累计', async ({ page }) => {
  await mockApi(page)
  const received = await mockAgent(page, (ws, msg) => {
    if (msg.message) {
      send(ws, { type: 'thinking' })
      send(ws, { type: 'tool_call_started', tool: 'get_quote', args: { code: '600519' } })
      send(ws, { type: 'tool_call_finished', tool: 'get_quote', status: 'done', elapsed_ms: 640, result: '贵州茅台 1680.5 +1.85%' })
      send(ws, { type: 'confirm_required', id: 'c1', tool: 'manage_watchlist', args: { code: '600519' }, description: '修改自选股：600519' })
    }
    if (msg.type === 'confirm') {
      send(ws, { type: 'tool_call_started', tool: 'manage_watchlist', args: { code: '600519' } })
      send(ws, { type: 'tool_call_finished', tool: 'manage_watchlist', status: 'done', elapsed_ms: 80, result: '已加入自选' })
      send(ws, { type: 'chunk', text: '已把**贵州茅台**加入自选。' })
      send(ws, { type: 'usage', prompt_tokens: 1000, completion_tokens: 234, total_tokens: 1234 })
      send(ws, { type: 'done', tools_used: ['get_quote', 'manage_watchlist'], rounds: 2 })
    }
  })
  await page.goto('/')
  await ask(page, '看下茅台并加入自选')

  await expect(page.getByTestId('confirm')).toContainText('修改自选股：600519')
  await expect(page.getByTestId('mascot-say')).toContainText('确认')
  await page.getByTestId('prompt').press('y')

  await expect(page.getByTestId('confirm')).toContainText('已允许')
  await expect(page.getByTestId('chat-log')).toContainText('已把贵州茅台加入自选。')
  await expect(page.getByTestId('timeline-row')).toHaveCount(2)
  await expect(page.getByTestId('timeline-stats')).toContainText('共 2')
  await expect(page.getByText('1,234 tokens')).toBeVisible()
  await expect(page.getByTestId('mascot-say')).toHaveText('赚到了！')
  expect(received).toContainEqual({ type: 'confirm', id: 'c1', decision: 'allow' })
})

test('esc 中断当前轮：发出 cancel，运行中的工具标为已中断', async ({ page }) => {
  await mockApi(page)
  const received = await mockAgent(page, (ws, msg) => {
    if (msg.message) {
      send(ws, { type: 'thinking' })
      send(ws, { type: 'tool_call_started', tool: 'get_fundamentals', args: { code: '300750' } })
    }
    if (msg.type === 'cancel') {
      send(ws, { type: 'interrupted' })
      send(ws, { type: 'done', tools_used: [], rounds: 1 })
    }
  })
  await page.goto('/')
  await ask(page, '宁德时代基本面')
  await expect(page.getByTestId('timeline-row')).toContainText('运行中')
  await page.getByTestId('prompt').press('Escape')
  await expect(page.getByTestId('timeline-row')).toContainText('已中断')
  await expect(page.getByTestId('chat-log')).toContainText('已中断，可继续输入新的指令')
  expect(received).toContainEqual({ type: 'cancel' })
})

test('/theme 切换主题：12 套主题的配色都生效', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  const bg = () => page.evaluate(() => getComputedStyle(document.body).backgroundColor)
  const seen = new Set<string>([await bg()])
  for (const t of ['light', 'tokyo-night', 'catppuccin-mocha', 'dracula', 'nord', 'gruvbox-dark', 'one-dark',
    'github-light', 'solarized-light', 'catppuccin-latte', 'rose-pine-dawn']) {
    await ask(page, `/theme ${t}`)
    await expect(page.locator('html')).toHaveAttribute('data-theme', t)
    seen.add(await bg())
  }
  expect(seen.size).toBe(12)
})

test('远程访问：先输入配对码', async ({ page }) => {
  await mockApi(page, { auth: 'pairing' })
  await page.goto('/')
  await expect(page.getByText('远程访问需要配对')).toBeVisible()
  await ask(page, '000000')
  await expect(page.getByText('配对码无效')).toBeVisible()
  await ask(page, '123456')
  await expect(page.getByText('✓ 配对成功')).toBeVisible()
  await expect(page.getByText('模型 deepseek-chat')).toBeVisible()
})

test('手机窄屏：时间线默认收起，/tools 以浮层打开', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockApi(page)
  await page.goto('/')
  await expect(page.getByText('工具调用时间线', { exact: true })).toBeHidden()
  await ask(page, '/tools')
  await expect(page.getByText('工具调用时间线', { exact: true })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})

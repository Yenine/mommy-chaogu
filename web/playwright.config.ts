import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  outputDir: '../output/playwright/results',
  reporter: [['list'], ['html', { outputFolder: '../output/playwright/report', open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:8765',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'uv run mommy-web --host 127.0.0.1 --port 8765',
    cwd: '..',
    url: 'http://127.0.0.1:8765/api/health',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      MOMMY_MARKET_DB: '/tmp/mommy-e2e-market.db',
      MOMMY_PORTFOLIO_DB: '/tmp/mommy-e2e-portfolio.db',
      MOMMY_AGENT_DB: '/tmp/mommy-e2e-agent.db',
      MOMMY_REFERENCE_DB: '/tmp/mommy-e2e-reference.db',
    },
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        // 本地可用 PW_CHROMIUM_PATH 指向已有的 Chromium（CI 用 playwright install 的版本）
        launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
      },
    },
  ],
})

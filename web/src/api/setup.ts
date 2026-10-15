/** Browser pairing API — /api/auth/pair（其余 setup 向导端点由终端 `mommy setup` 使用，前端无封装）。 */

import { apiFetch } from './client'

export interface PairResult {
  ok: boolean
  message: string
}

export async function submitPairingCode(code: string): Promise<PairResult> {
  const res = await apiFetch('/api/auth/pair', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  })
  const body = await res.json() as { ok?: boolean; message?: string }
  return {
    ok: res.ok && body.ok === true,
    message: body.message || (res.ok ? '配对成功' : '配对失败，请重试'),
  }
}

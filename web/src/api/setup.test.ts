import { beforeEach, describe, expect, it, vi } from 'vitest'

import { submitPairingCode } from './setup'

describe('setup API', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  it('submitPairingCode calls POST /api/auth/pair', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true, message: '配对成功' }), { status: 200 }),
    )
    const result = await submitPairingCode('123456')
    expect(result.ok).toBe(true)
    const call = vi.mocked(fetch).mock.calls[0]
    expect(call?.[0]).toBe('/api/auth/pair')
    const body = JSON.parse(call?.[1]?.body as string)
    expect(body.code).toBe('123456')
  })

  it('submitPairingCode preserves the safe server message on a rejected code', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: false, message: '配对码无效或已过期，请重启服务获取新码' }), { status: 401 }),
    )
    const result = await submitPairingCode('000000')
    expect(result).toEqual({
      ok: false,
      message: '配对码无效或已过期，请重启服务获取新码',
    })
    expect(fetch).toHaveBeenCalledWith(
      '/api/auth/pair',
      expect.objectContaining({ credentials: 'include' }),
    )
  })
})

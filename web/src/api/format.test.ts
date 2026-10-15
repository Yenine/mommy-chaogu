import { describe, expect, it } from 'vitest'

import { fmtMoney, fmtPct, fmtPrice } from './index'

describe('market formatting', () => {
  it('formats prices, percentages, and money', () => {
    expect(fmtPrice('12.345')).toBe('12.35')
    expect(fmtPct('1.2')).toBe('+1.20%')
    expect(fmtPct('-1.2')).toBe('-1.20%')
    expect(fmtMoney('250000000', 'yi')).toBe('2.50亿')
    expect(fmtMoney(undefined)).toBe('-')
  })
})

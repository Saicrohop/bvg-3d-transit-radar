import { describe, expect, it } from 'vitest'

import {
  getBerlinTransitLineColor,
  getBerlinTransitLineColorRgb,
} from './berlinTransitColors'

describe('Berlin S-Bahn and U-Bahn line colors', () => {
  it.each([
    ['S1', 's_bahn', '#da6ba2'],
    ['S15', 's_bahn', '#da6ba2'],
    ['S2', 's_bahn', '#007734'],
    ['S25', 's_bahn', '#007734'],
    ['S26', 's_bahn', '#007734'],
    ['S3', 's_bahn', '#0066ad'],
    ['S41', 's_bahn', '#ad5937'],
    ['S42', 's_bahn', '#cb6418'],
    ['S46', 's_bahn', '#cd9c53'],
    ['S47', 's_bahn', '#cd9c53'],
    ['S5', 's_bahn', '#eb7405'],
    ['S7', 's_bahn', '#816da6'],
    ['S75', 's_bahn', '#816da6'],
    ['S8', 's_bahn', '#66aa22'],
    ['S85', 's_bahn', '#66aa22'],
    ['S9', 's_bahn', '#992746'],
    ['U1', 'u_bahn', '#7dad4c'],
    ['U2', 'u_bahn', '#da421e'],
    ['U3', 'u_bahn', '#16683d'],
    ['U4', 'u_bahn', '#f0d722'],
    ['U5', 'u_bahn', '#7e5330'],
    ['U6', 'u_bahn', '#8c6dab'],
    ['U7', 'u_bahn', '#009bd5'],
    ['U8', 'u_bahn', '#224f86'],
    ['U9', 'u_bahn', '#f3791d'],
  ] as const)('uses the official color for %s', (line, category, color) => {
    expect(getBerlinTransitLineColor(line, category)).toBe(color)
  })

  it('normalizes case and whitespace and prefers a known line over category', () => {
    expect(getBerlinTransitLineColor(' u 4 ', 's_bahn')).toBe('#f0d722')
  })

  it('keeps existing category colors for non-rail lines and unknown routes', () => {
    expect(getBerlinTransitLineColor('M10', 'tram')).toBe('#ff967c')
    expect(getBerlinTransitLineColor(null, 's_bahn')).toBe('#76ffc2')
    expect(getBerlinTransitLineColor(null, null)).toBe('#e7ff49')
  })

  it('provides RGB channels for Deck accessors', () => {
    expect(getBerlinTransitLineColorRgb('S7', 's_bahn')).toEqual([129, 109, 166])
  })
})

// @vitest-environment jsdom

import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { MOCK_CALIBRATION_VEHICLES } from '../map/scenegraphCalibration'
import { useScenegraphCalibration } from './useScenegraphCalibration'

describe('useScenegraphCalibration', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('reveals the prescribed mock vehicles one second after calibration is enabled', () => {
    const { result } = renderHook(() => useScenegraphCalibration(true))

    expect(result.current).toEqual([])

    act(() => {
      vi.advanceTimersByTime(1_000)
    })

    expect(result.current).toEqual(MOCK_CALIBRATION_VEHICLES)
  })
})

// @vitest-environment jsdom

import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createEstimatedVehiclePosition } from '../test/estimatedVehiclePositionFixture'
import { useEstimatedVehiclePositions } from './useEstimatedVehiclePositions'
import type { EstimatedVehiclePosition, VehiclePositionSnapshot } from './vehiclePositions'

const url = 'ws://127.0.0.1:8000/ws/positions'
const NOW = Date.parse('2026-07-19T10:40:00.123Z')
const firstPosition = createEstimatedVehiclePosition()

function snapshot(
  positions: readonly EstimatedVehiclePosition[] = [firstPosition],
  overrides: Partial<VehiclePositionSnapshot> = {},
): VehiclePositionSnapshot {
  return {
    type: 'vehicle_position_snapshot',
    schema_version: 1,
    cycle_id: 'cycle-1',
    feed_timestamp: firstPosition.feed_timestamp,
    observed_at: firstPosition.observed_at,
    positions,
    statistics: {
      trip_updates_received: positions.length,
      positions_estimated: positions.length,
      positions_suppressed: 0,
    },
    ...overrides,
  }
}

function currentSnapshot(overrides: Partial<EstimatedVehiclePosition> = {}) {
  const position = createEstimatedVehiclePosition({
    feed_timestamp: '2026-07-19T10:40:00Z',
    observed_at: '2026-07-19T10:40:00Z',
    ...overrides,
  })
  return snapshot([position], {
    feed_timestamp: position.feed_timestamp,
    observed_at: position.observed_at,
  })
}

class FakeWebSocket {
  static instances: FakeWebSocket[] = []

  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((event: MessageEvent<unknown>) => void) | null = null
  onopen: (() => void) | null = null
  readonly close = vi.fn()
  readonly url: string

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  emit(data: unknown) {
    this.onmessage?.(new MessageEvent('message', { data }))
  }

  emitJson(event: unknown) {
    this.emit(JSON.stringify(event))
  }
}

describe('useEstimatedVehiclePositions', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(NOW)
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('immediately replaces the whole snapshot and removes absent trips', () => {
    const { result } = renderHook(() => useEstimatedVehiclePositions(url))
    const socket = FakeWebSocket.instances[0]
    const positionB = createEstimatedVehiclePosition({ trip_id: 'B' })
    const first = snapshot([firstPosition, positionB])

    act(() => socket.emitJson(first))
    expect(result.current.vehicles).toEqual(first.positions)
    expect(result.current.snapshot).toEqual(first)
    expect(result.current.vehicles).toBe(result.current.snapshot?.positions)

    const second = snapshot([
      { ...positionB, longitude: 13.5 },
      createEstimatedVehiclePosition({ trip_id: 'C' }),
    ], { cycle_id: 'cycle-2' })
    act(() => socket.emitJson(second))
    expect(result.current.vehicles).toEqual(second.positions)
    expect(result.current.snapshot).toEqual(second)
    expect(result.current.vehicles).toBe(result.current.snapshot?.positions)
  })

  it('keeps rejected input distinct from valid empty snapshots and counts only active rejections', () => {
    const { result } = renderHook(() => useEstimatedVehiclePositions(url))
    const socket = FakeWebSocket.instances[0]
    act(() => socket.emitJson(snapshot()))
    const accepted = result.current.snapshot
    act(() => socket.emit('invalid JSON'))
    expect(result.current.snapshot).toBe(accepted)
    expect(result.current.rejectedMessages).toBe(1)
    act(() => socket.emitJson(snapshot([], { schema_version: 2 } as unknown as Partial<VehiclePositionSnapshot>)))
    expect(result.current.snapshot).toBe(accepted)
    expect(result.current.rejectedMessages).toBe(2)
    act(() => socket.emitJson(snapshot([])))
    expect(result.current.vehicles).toEqual([])
    expect(result.current.snapshot).not.toBeNull()
    expect(result.current.rejectedMessages).toBe(2)
  })

  it('preserves the last snapshot while an unexpected close schedules one reconnect', () => {
    vi.spyOn(Math, 'random').mockReturnValue(0.5)
    const { result } = renderHook(() => useEstimatedVehiclePositions(url))
    const first = FakeWebSocket.instances[0]
    const accepted = currentSnapshot()

    act(() => {
      first.onopen?.()
      first.emitJson(accepted)
      first.onclose?.()
    })
    expect(result.current.connectionStatus).toBe('reconnecting')
    expect(result.current.snapshot).toEqual(accepted)
    expect(result.current.dataStatus).toBe('fresh')
    expect(FakeWebSocket.instances).toHaveLength(1)

    act(() => vi.advanceTimersByTime(999))
    expect(FakeWebSocket.instances).toHaveLength(1)
    act(() => vi.advanceTimersByTime(1))
    expect(FakeWebSocket.instances).toHaveLength(2)
    expect(result.current.connectionStatus).toBe('reconnecting')

    const second = FakeWebSocket.instances[1]
    act(() => second.onopen?.())
    expect(result.current.connectionStatus).toBe('open')
    expect(result.current.snapshot).toEqual(accepted)
  })

  it('does not schedule duplicate reconnects when error is followed by close', () => {
    vi.spyOn(Math, 'random').mockReturnValue(0.5)
    const { result } = renderHook(() => useEstimatedVehiclePositions(url))
    const socket = FakeWebSocket.instances[0]

    act(() => {
      socket.onerror?.()
      socket.onclose?.()
    })
    expect(result.current.connectionStatus).toBe('error')
    act(() => vi.advanceTimersByTime(1_000))
    expect(FakeWebSocket.instances).toHaveLength(2)
    act(() => vi.advanceTimersByTime(30_000))
    expect(FakeWebSocket.instances).toHaveLength(2)
  })

  it('keeps exponential backoff after open until a valid snapshot proves progress', () => {
    vi.spyOn(Math, 'random').mockReturnValue(0.5)
    const { result } = renderHook(() => useEstimatedVehiclePositions(url))
    const first = FakeWebSocket.instances[0]

    act(() => first.onclose?.())
    act(() => vi.advanceTimersByTime(1_000))
    const second = FakeWebSocket.instances[1]
    expect(result.current.connectionStatus).toBe('reconnecting')
    act(() => second.onclose?.())
    act(() => vi.advanceTimersByTime(1_999))
    expect(FakeWebSocket.instances).toHaveLength(2)
    act(() => vi.advanceTimersByTime(1))
    expect(FakeWebSocket.instances).toHaveLength(3)

    const third = FakeWebSocket.instances[2]
    act(() => {
      third.onopen?.()
      third.onclose?.()
    })
    act(() => third.emit('invalid JSON'))
    act(() => vi.advanceTimersByTime(3_999))
    expect(FakeWebSocket.instances).toHaveLength(3)
    act(() => vi.advanceTimersByTime(1))
    expect(FakeWebSocket.instances).toHaveLength(4)
    const fourth = FakeWebSocket.instances[3]
    act(() => { fourth.onopen?.(); fourth.emitJson(currentSnapshot()); fourth.onclose?.() })
    act(() => vi.advanceTimersByTime(999))
    expect(FakeWebSocket.instances).toHaveLength(4)
    act(() => vi.advanceTimersByTime(1))
    expect(FakeWebSocket.instances).toHaveLength(5)
  })

  it('marks data stale after 45 seconds without a new valid snapshot', () => {
    const futureWithinSkew = currentSnapshot({
      feed_timestamp: '2026-07-19T10:40:04Z',
      observed_at: '2026-07-19T10:40:04Z',
    })
    const { result } = renderHook(() => useEstimatedVehiclePositions(url))
    const socket = FakeWebSocket.instances[0]

    act(() => socket.emitJson(futureWithinSkew))
    expect(result.current.dataStatus).toBe('fresh')
    act(() => vi.advanceTimersByTime(44_999))
    expect(result.current.dataStatus).toBe('fresh')
    act(() => vi.advanceTimersByTime(1))
    expect(result.current.dataStatus).toBe('stale')
    expect(result.current.dataStatusReason).toBe('no_recent_snapshot')
    expect(result.current.snapshot).toEqual(futureWithinSkew)
  })

  it('marks an accepted replay with old provenance stale immediately', () => {
    const old = currentSnapshot({
      feed_timestamp: '2026-07-19T10:38:20Z',
      observed_at: '2026-07-19T10:38:20Z',
    })
    const { result } = renderHook(() => useEstimatedVehiclePositions(url))

    act(() => FakeWebSocket.instances[0].emitJson(old))
    expect(result.current.snapshot).toEqual(old)
    expect(result.current.dataStatus).toBe('stale')
    expect(result.current.dataStatusReason).toBe('old_snapshot')
  })

  it('does not refresh freshness after invalid input', () => {
    const { result } = renderHook(() => useEstimatedVehiclePositions(url))
    const socket = FakeWebSocket.instances[0]
    const accepted = currentSnapshot()

    act(() => socket.emitJson(accepted))
    act(() => vi.advanceTimersByTime(44_000))
    act(() => socket.emit('invalid JSON'))
    expect(result.current.rejectedMessages).toBe(1)
    act(() => vi.advanceTimersByTime(1_000))
    expect(result.current.dataStatus).toBe('stale')
    expect(result.current.dataStatusReason).toBe('old_snapshot')
    expect(result.current.snapshot).toEqual(accepted)
  })

  it('cancels reconnect timers and ignores obsolete callbacks on unmount', () => {
    const { result, unmount } = renderHook(() => useEstimatedVehiclePositions(url))
    const old = FakeWebSocket.instances[0]
    act(() => old.onclose?.())
    unmount()
    act(() => {
      vi.advanceTimersByTime(30_000)
      old.onopen?.()
      old.emitJson(currentSnapshot())
    })
    expect(FakeWebSocket.instances).toHaveLength(1)
    expect(result.current.connectionStatus).toBe('reconnecting')
    expect(old.close).not.toHaveBeenCalled()
  })

  it('starts a new endpoint empty and ignores every obsolete socket callback', () => {
    const { result, rerender, unmount } = renderHook(({ endpoint }) => useEstimatedVehiclePositions(endpoint), { initialProps: { endpoint: url } })
    const old = FakeWebSocket.instances[0]
    act(() => { old.onopen?.(); old.emitJson(currentSnapshot()); old.emit('invalid') })
    rerender({ endpoint: 'ws://127.0.0.1:8766/ws/positions' })
    expect(old.close).toHaveBeenCalledOnce()
    expect(result.current.connectionStatus).toBe('connecting')
    expect(result.current.snapshot).toBeNull()
    expect(result.current.rejectedMessages).toBe(0)
    act(() => { old.onopen?.(); old.onerror?.(); old.onclose?.(); old.emitJson(currentSnapshot()); old.emit('invalid') })
    expect(result.current.connectionStatus).toBe('connecting')
    expect(result.current.vehicles).toEqual([])
    expect(result.current.rejectedMessages).toBe(0)
    const current = FakeWebSocket.instances[1]
    act(() => { current.onopen?.(); current.emitJson(currentSnapshot()) })
    expect(result.current.connectionStatus).toBe('open')
    expect(result.current.vehicles).toHaveLength(1)
    act(() => current.onclose?.())
    expect(result.current.connectionStatus).toBe('reconnecting')
    act(() => { current.emitJson(snapshot([])); current.emit('invalid'); current.onopen?.() })
    expect(result.current.connectionStatus).toBe('reconnecting')
    expect(result.current.vehicles).toHaveLength(1)
    unmount()
    expect(current.close).not.toHaveBeenCalled()
  })

  it('surfaces an invalid WebSocket URL without crashing the render tree', () => {
    vi.stubGlobal('WebSocket', class { constructor() { throw new DOMException('Invalid URL', 'SyntaxError') } })
    const { result } = renderHook(() => useEstimatedVehiclePositions('not a URL'))
    expect(result.current.connectionStatus).toBe('error')
    expect(result.current.snapshot).toBeNull()
  })
})

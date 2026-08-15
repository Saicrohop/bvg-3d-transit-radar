// @vitest-environment jsdom

import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  POSITION_BATCH_QUIET_PERIOD_MS,
  useEstimatedVehiclePositions,
} from './useEstimatedVehiclePositions'

const firstEvent = {
  type: 'vehicle_position',
  source: 'trip_update_interpolation',
  is_estimated: true,
  vehicle_category: 's_bahn',
  trip_id: 'trip-42',
  route_id: 'route-7',
  route_short_name: 'S41',
  longitude: 13.401,
  latitude: 52.501,
  bearing_degrees: 91.5,
  speed_mps: 8.2,
}

const legacyEventWithoutCategory = {
  type: 'vehicle_position',
  source: 'trip_update_interpolation',
  is_estimated: true,
  trip_id: 'legacy-trip',
  route_id: 'legacy-route',
  longitude: 13.402,
  latitude: 52.502,
  bearing_degrees: 92,
  speed_mps: 8.3,
}

class FakeWebSocket {
  static instances: FakeWebSocket[] = []

  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onopen: (() => void) | null = null
  readonly close = vi.fn()
  readonly url: string

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  emitJson(event: unknown) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(event) }))
  }
}

describe('useEstimatedVehiclePositions', () => {
  beforeEach(() => {
    FakeWebSocket.instances = []
    vi.useFakeTimers()
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('replaces an active vehicle with the latest event for its trip', () => {
    const { result, unmount } = renderHook(() =>
      useEstimatedVehiclePositions('ws://127.0.0.1:8000/ws/positions'),
    )
    const socket = FakeWebSocket.instances[0]

    act(() => {
      socket.emitJson(firstEvent)
      socket.emitJson({ ...firstEvent, longitude: 13.405, latitude: 52.52 })
      vi.advanceTimersByTime(POSITION_BATCH_QUIET_PERIOD_MS)
    })

    expect(result.current.vehicles).toEqual([
      { ...firstEvent, longitude: 13.405, latitude: 52.52 },
    ])

    unmount()
    expect(socket.close).toHaveBeenCalledOnce()
  })

  it('normalizes a legacy event without vehicle_category to the 2D fallback category', () => {
    const { result } = renderHook(() =>
      useEstimatedVehiclePositions('ws://127.0.0.1:8000/ws/positions'),
    )
    const socket = FakeWebSocket.instances[0]

    act(() => {
      socket.emitJson(legacyEventWithoutCategory)
      vi.advanceTimersByTime(POSITION_BATCH_QUIET_PERIOD_MS)
    })

    expect(result.current.vehicles).toEqual([
      {
        ...legacyEventWithoutCategory,
        vehicle_category: null,
        route_short_name: null,
      },
    ])
  })

  it('publishes a WebSocket burst once after the quiet period', () => {
    let renderCount = 0
    const { result } = renderHook(() => {
      renderCount += 1
      return useEstimatedVehiclePositions(
        'ws://127.0.0.1:8000/ws/positions',
      )
    })
    const socket = FakeWebSocket.instances[0]

    act(() => {
      socket.emitJson(firstEvent)
      socket.emitJson({
        ...firstEvent,
        trip_id: 'trip-43',
        route_short_name: 'S42',
      })
      socket.emitJson({ ...firstEvent, longitude: 13.405, latitude: 52.52 })
    })

    expect(result.current.vehicles).toEqual([])
    expect(renderCount).toBe(1)

    act(() => {
      vi.advanceTimersByTime(POSITION_BATCH_QUIET_PERIOD_MS - 1)
    })

    expect(result.current.vehicles).toEqual([])
    expect(renderCount).toBe(1)

    act(() => {
      vi.advanceTimersByTime(1)
    })

    expect(result.current.vehicles).toEqual([
      { ...firstEvent, longitude: 13.405, latitude: 52.52 },
      {
        ...firstEvent,
        trip_id: 'trip-43',
        route_short_name: 'S42',
      },
    ])
    expect(renderCount).toBe(2)
  })
})

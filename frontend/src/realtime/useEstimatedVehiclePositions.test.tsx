// @vitest-environment jsdom

import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useEstimatedVehiclePositions } from './useEstimatedVehiclePositions'

const firstEvent = {
  type: 'vehicle_position',
  source: 'trip_update_interpolation',
  is_estimated: true,
  vehicle_category: 's_bahn',
  trip_id: 'trip-42',
  route_id: 'route-7',
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
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })

  afterEach(() => {
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
    })

    expect(result.current.vehicles).toEqual([
      { ...legacyEventWithoutCategory, vehicle_category: null },
    ])
  })
})

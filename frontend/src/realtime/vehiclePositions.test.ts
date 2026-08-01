import { describe, expect, it } from 'vitest'

import {
  isEstimatedVehiclePosition,
  normalizeEstimatedVehiclePosition,
  upsertVehiclePosition,
  type EstimatedVehiclePosition,
} from './vehiclePositions'

const firstPosition: EstimatedVehiclePosition = {
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

describe('vehicle position state', () => {
  it('replaces the previous position for the same trip without duplication', () => {
    const updatedPosition = { ...firstPosition, longitude: 13.405, latitude: 52.52 }

    const positions = upsertVehiclePosition(
      upsertVehiclePosition({}, firstPosition),
      updatedPosition,
    )

    expect(Object.keys(positions)).toEqual(['trip-42'])
    expect(positions['trip-42']).toEqual(updatedPosition)
  })

  it('normalizes a legacy missing category while rejecting malformed events', () => {
    expect(
      isEstimatedVehiclePosition({
        ...firstPosition,
        vehicle_category: 's_bahn',
      }),
    ).toBe(true)
    const legacyPositionWithoutCategory = {
      type: 'vehicle_position' as const,
      source: 'trip_update_interpolation' as const,
      is_estimated: true as const,
      trip_id: 'trip-42',
      route_id: 'route-7',
      longitude: 13.401,
      latitude: 52.501,
      bearing_degrees: 91.5,
      speed_mps: 8.2,
    }

    expect(isEstimatedVehiclePosition(legacyPositionWithoutCategory)).toBe(true)
    if (!isEstimatedVehiclePosition(legacyPositionWithoutCategory)) {
      throw new Error('Expected the legacy estimated-position payload to parse')
    }
    expect(normalizeEstimatedVehiclePosition(legacyPositionWithoutCategory)).toEqual({
      ...legacyPositionWithoutCategory,
      vehicle_category: null,
    })
    expect(
      isEstimatedVehiclePosition({
        ...firstPosition,
        is_estimated: false,
      }),
    ).toBe(false)
    expect(
      isEstimatedVehiclePosition({
        ...firstPosition,
        vehicle_category: 'ferry',
      }),
    ).toBe(false)
    expect(isEstimatedVehiclePosition({ type: 'feed_message' })).toBe(false)
  })
})

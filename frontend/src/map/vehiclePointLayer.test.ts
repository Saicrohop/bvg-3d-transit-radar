import { describe, expect, it } from 'vitest'

import {
  createVehiclePointLayer,
  getVehiclePosition,
  VEHICLE_FILL_COLOR,
} from './vehiclePointLayer'

const vehicle = {
  type: 'vehicle_position' as const,
  source: 'trip_update_interpolation' as const,
  is_estimated: true as const,
  vehicle_category: null,
  trip_id: 'trip-42',
  route_id: 'route-7',
  longitude: 13.405,
  latitude: 52.52,
  bearing_degrees: 91.5,
  speed_mps: 8.2,
}

describe('createVehiclePointLayer', () => {
  it('maps an estimated vehicle to its WGS84 longitude and latitude', () => {
    const layer = createVehiclePointLayer([vehicle])

    expect(layer.id).toBe('estimated-vehicle-points')
    expect(getVehiclePosition(vehicle)).toEqual([13.405, 52.52])
    expect(VEHICLE_FILL_COLOR).toEqual([255, 210, 0])
  })
})

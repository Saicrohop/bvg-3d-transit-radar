import { describe, expect, it } from 'vitest'
import type { EstimatedVehiclePosition } from '../realtime/vehiclePositions'

import {
  createVehiclePointLayer,
  getVehiclePosition,
  VEHICLE_FILL_COLOR,
} from './vehiclePointLayer'

const vehicle = {
  type: 'vehicle_position' as const,
  source: 'trip_update_interpolation' as const,
  is_estimated: true as const,
  position_status: 'estimated_from_trip_update' as const,
  timing_source: 'schedule_only' as const,
  delay_seconds: null,
  feed_timestamp: null,
  trip_update_timestamp: null,
  service_date: '2026-07-19',
  entity_id: 'test-entity',
  shape_id: 'test-shape',
  previous_stop_id: 'test-stop-a',
  next_stop_id: 'test-stop-b',
  estimated_next_arrival: '2026-07-19T12:02:00Z',
  observed_at: '2026-07-19T12:00:00Z',
  vehicle_category: null,
  trip_id: 'trip-42',
  route_id: 'route-7',
  route_short_name: null,
  longitude: 13.405,
  latitude: 52.52,
  bearing_degrees: 91.5,
  speed_mps: 8.2,
}

describe('createVehiclePointLayer', () => {
  it('maps an estimated vehicle to its WGS84 longitude and latitude', () => {
    const layer = createVehiclePointLayer([vehicle])

    expect(layer.id).toBe('estimated-vehicle-points')
    expect(layer.props.transitions).toEqual({ getPosition: 1000 })
    expect(getVehiclePosition(vehicle)).toEqual([13.405, 52.52])
    const getFillColor = layer.props.getFillColor as unknown as (
      currentVehicle: EstimatedVehiclePosition,
    ) => readonly number[]
    expect(getFillColor(vehicle)).toEqual(VEHICLE_FILL_COLOR)
    expect(
      getFillColor({
        ...vehicle,
        vehicle_category: 's_bahn',
        route_short_name: 'S41',
      }),
    ).toEqual([173, 89, 55])
  })
})

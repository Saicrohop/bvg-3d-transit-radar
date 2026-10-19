import type { EstimatedVehiclePosition } from '../realtime/vehiclePositions'

export function createEstimatedVehiclePosition(
  overrides: Partial<EstimatedVehiclePosition> = {},
): EstimatedVehiclePosition {
  return {
    type: 'vehicle_position',
    source: 'trip_update_interpolation',
    is_estimated: true,
    position_status: 'estimated_from_trip_update',
    timing_source: 'schedule_only',
    delay_seconds: null,
    feed_timestamp: '2026-07-19T10:38:20Z',
    trip_update_timestamp: null,
    service_date: '2026-07-19',
    vehicle_category: 's_bahn',
    route_short_name: 'S41',
    entity_id: 'entity-42',
    trip_id: 'trip-42',
    route_id: 'route-7',
    shape_id: 'shape-7',
    previous_stop_id: 'stop-1',
    next_stop_id: 'stop-2',
    estimated_next_arrival: '2026-07-19T10:42:00Z',
    longitude: 13.401,
    latitude: 52.501,
    bearing_degrees: 91.5,
    speed_mps: 8.2,
    observed_at: '2026-07-19T10:40:00.123456Z',
    ...overrides,
  }
}

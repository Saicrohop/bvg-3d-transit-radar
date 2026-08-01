export const VEHICLE_CATEGORIES = ['u_bahn', 's_bahn', 'bus', 'tram'] as const

export type VehicleCategory = (typeof VEHICLE_CATEGORIES)[number]

export type EstimatedVehiclePosition = Readonly<{
  type: 'vehicle_position'
  source: 'trip_update_interpolation'
  is_estimated: true
  vehicle_category: VehicleCategory | null
  trip_id: string
  route_id: string
  longitude: number
  latitude: number
  bearing_degrees: number
  speed_mps: number
}>

export type EstimatedVehiclePositionPayload = Readonly<
  Omit<EstimatedVehiclePosition, 'vehicle_category'> & {
    vehicle_category?: VehicleCategory | null
  }
>

export type VehiclePositionsByTrip = Readonly<
  Record<string, EstimatedVehiclePosition>
>

export function isEstimatedVehiclePosition(
  value: unknown,
): value is EstimatedVehiclePositionPayload {
  if (typeof value !== 'object' || value === null) {
    return false
  }

  const event = value as Record<string, unknown>
  return (
    event.type === 'vehicle_position' &&
    event.source === 'trip_update_interpolation' &&
    event.is_estimated === true &&
    isOptionalVehicleCategory(event.vehicle_category) &&
    typeof event.trip_id === 'string' &&
    event.trip_id.length > 0 &&
    typeof event.route_id === 'string' &&
    event.route_id.length > 0 &&
    isFiniteNumber(event.longitude) &&
    isFiniteNumber(event.latitude) &&
    isFiniteNumber(event.bearing_degrees) &&
    isFiniteNumber(event.speed_mps)
  )
}

export function normalizeEstimatedVehiclePosition(
  position: EstimatedVehiclePositionPayload,
): EstimatedVehiclePosition {
  return {
    ...position,
    vehicle_category: position.vehicle_category ?? null,
  }
}

export function upsertVehiclePosition(
  positions: VehiclePositionsByTrip,
  position: EstimatedVehiclePosition,
): VehiclePositionsByTrip {
  return { ...positions, [position.trip_id]: position }
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function isVehicleCategory(value: unknown): value is VehicleCategory | null {
  return value === null || VEHICLE_CATEGORIES.includes(value as VehicleCategory)
}

function isOptionalVehicleCategory(
  value: unknown,
): value is VehicleCategory | null | undefined {
  return value === undefined || isVehicleCategory(value)
}

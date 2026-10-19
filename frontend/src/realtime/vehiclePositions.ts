export const VEHICLE_CATEGORIES = [
  'u_bahn',
  's_bahn',
  'bus',
  'tram',
  'regional',
] as const

export type VehicleCategory = (typeof VEHICLE_CATEGORIES)[number]

export const TIMING_SOURCES = [
  'absolute_realtime_time',
  'realtime_delay',
  'schedule_only',
] as const

export type TimingSource = (typeof TIMING_SOURCES)[number]

export type EstimatedVehiclePosition = Readonly<{
  type: 'vehicle_position'
  source: 'trip_update_interpolation'
  is_estimated: true
  position_status: 'estimated_from_trip_update'
  timing_source: TimingSource
  delay_seconds: number | null
  feed_timestamp: string | null
  trip_update_timestamp: string | null
  service_date: string
  vehicle_category: VehicleCategory | null
  entity_id: string
  shape_id: string
  previous_stop_id: string
  next_stop_id: string
  estimated_next_arrival: string
  observed_at: string
  trip_id: string
  route_id: string
  route_short_name: string | null
  longitude: number
  latitude: number
  bearing_degrees: number
  speed_mps: number
}>

export type VehiclePositionSnapshotStatistics = Readonly<{
  trip_updates_received: number
  positions_estimated: number
  positions_suppressed: number
}>

export type VehiclePositionSnapshot = Readonly<{
  type: 'vehicle_position_snapshot'
  schema_version: 1
  cycle_id: string
  feed_timestamp: string | null
  observed_at: string
  positions: readonly EstimatedVehiclePosition[]
  statistics: VehiclePositionSnapshotStatistics
}>

export function parseVehiclePositionSnapshotMessage(
  data: unknown,
): VehiclePositionSnapshot | null {
  if (typeof data !== 'string') {
    return null
  }
  try {
    const event: unknown = JSON.parse(data)
    if (
      !isRecord(event) || event.type !== 'vehicle_position_snapshot' ||
      event.schema_version !== 1 ||
      typeof event.cycle_id !== 'string' || event.cycle_id.trim().length === 0 ||
      !isNullableTimestamp(event.feed_timestamp) || !isUtcTimestamp(event.observed_at)
    ) {
      return null
    }
    if (!Array.isArray(event.positions) ||
      !isSnapshotStatistics(event.statistics, event.positions.length)) {
      return null
    }
    const positions: EstimatedVehiclePosition[] = []
    const tripIds = new Set<string>()
    for (const position of event.positions) {
      if (
        !isEstimatedVehiclePosition(position) || tripIds.has(position.trip_id) ||
        position.feed_timestamp !== event.feed_timestamp ||
        position.observed_at !== event.observed_at
      ) {
        return null
      }
      tripIds.add(position.trip_id)
      positions.push(copyPosition(position))
    }
    return {
      type: event.type,
      schema_version: event.schema_version,
      cycle_id: event.cycle_id,
      feed_timestamp: event.feed_timestamp,
      observed_at: event.observed_at,
      positions,
      statistics: {
        trip_updates_received: event.statistics.trip_updates_received,
        positions_estimated: event.statistics.positions_estimated,
        positions_suppressed: event.statistics.positions_suppressed,
      },
    }
  } catch {
    return null
  }
}

export type EstimatedVehiclePositionPayload = Readonly<
  Omit<EstimatedVehiclePosition, 'route_short_name' | 'vehicle_category'> & {
    vehicle_category?: VehicleCategory | null
    route_short_name?: string | null
  }
>

export type VehiclePositionsByTrip = Readonly<
  Record<string, EstimatedVehiclePosition>
>

export function isEstimatedVehiclePosition(
  value: unknown,
): value is EstimatedVehiclePosition {
  if (typeof value !== 'object' || value === null) {
    return false
  }

  const event = value as Record<string, unknown>
  return (
    event.type === 'vehicle_position' &&
    event.source === 'trip_update_interpolation' &&
    event.is_estimated === true &&
    event.position_status === 'estimated_from_trip_update' &&
    isTimingSource(event.timing_source) &&
    hasConsistentTimingEvidence(event.timing_source, event.delay_seconds) &&
    isNullableTimestamp(event.feed_timestamp) &&
    isNullableTimestamp(event.trip_update_timestamp) &&
    isServiceDate(event.service_date) &&
    isVehicleCategory(event.vehicle_category) &&
    typeof event.entity_id === 'string' &&
    typeof event.shape_id === 'string' &&
    typeof event.previous_stop_id === 'string' &&
    typeof event.next_stop_id === 'string' &&
    isUtcTimestamp(event.estimated_next_arrival) &&
    isUtcTimestamp(event.observed_at) &&
    typeof event.trip_id === 'string' &&
    event.trip_id.length > 0 &&
    typeof event.route_id === 'string' &&
    event.route_id.length > 0 &&
    isNullableString(event.route_short_name) &&
    isFiniteNumber(event.longitude) && Math.abs(event.longitude) <= 180 &&
    isFiniteNumber(event.latitude) && Math.abs(event.latitude) <= 90 &&
    isFiniteNumber(event.bearing_degrees) &&
    isFiniteNumber(event.speed_mps) && event.speed_mps >= 0
  )
}

export function normalizeEstimatedVehiclePosition(
  position: EstimatedVehiclePositionPayload,
): EstimatedVehiclePosition {
  return {
    ...position,
    vehicle_category: position.vehicle_category ?? null,
    route_short_name: position.route_short_name ?? null,
  }
}

export function upsertVehiclePosition(
  positions: VehiclePositionsByTrip,
  position: EstimatedVehiclePosition,
): VehiclePositionsByTrip {
  return { ...positions, [position.trip_id]: position }
}

function copyPosition(position: EstimatedVehiclePosition): EstimatedVehiclePosition {
  return {
    type: position.type,
    source: position.source,
    is_estimated: position.is_estimated,
    position_status: position.position_status,
    timing_source: position.timing_source,
    feed_timestamp: position.feed_timestamp,
    trip_update_timestamp: position.trip_update_timestamp,
    service_date: position.service_date,
    vehicle_category: position.vehicle_category,
    route_short_name: position.route_short_name,
    entity_id: position.entity_id,
    trip_id: position.trip_id,
    route_id: position.route_id,
    shape_id: position.shape_id,
    previous_stop_id: position.previous_stop_id,
    next_stop_id: position.next_stop_id,
    delay_seconds: position.delay_seconds,
    estimated_next_arrival: position.estimated_next_arrival,
    longitude: position.longitude,
    latitude: position.latitude,
    bearing_degrees: position.bearing_degrees,
    speed_mps: position.speed_mps,
    observed_at: position.observed_at,
  }
}

function isSnapshotStatistics(
  value: unknown,
  positionCount: number,
): value is VehiclePositionSnapshotStatistics {
  if (!isRecord(value)) {
    return false
  }
  return (
    isNonnegativeSafeInteger(value.trip_updates_received) &&
    isNonnegativeSafeInteger(value.positions_estimated) &&
    isNonnegativeSafeInteger(value.positions_suppressed) &&
    value.positions_estimated === positionCount &&
    value.positions_estimated + value.positions_suppressed === value.trip_updates_received
  )
}

function isNonnegativeSafeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function isTimingSource(value: unknown): value is TimingSource {
  return TIMING_SOURCES.includes(value as TimingSource)
}

function hasConsistentTimingEvidence(
  timingSource: TimingSource,
  delaySeconds: unknown,
): delaySeconds is number | null {
  if (timingSource === 'schedule_only') {
    return delaySeconds === null
  }
  return typeof delaySeconds === 'number' && Number.isInteger(delaySeconds)
}

const UTC_TIMESTAMP_PATTERN =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?Z$/

function isNullableTimestamp(value: unknown): value is string | null {
  return value === null || isUtcTimestamp(value)
}

function isUtcTimestamp(value: unknown): value is string {
  if (typeof value !== 'string') {
    return false
  }
  const match = UTC_TIMESTAMP_PATTERN.exec(value)
  if (match === null) {
    return false
  }
  const parsed = Date.parse(value)
  if (!Number.isFinite(parsed)) {
    return false
  }
  const timestamp = new Date(parsed)
  return (
    timestamp.getUTCFullYear() === Number(match[1]) &&
    timestamp.getUTCMonth() + 1 === Number(match[2]) &&
    timestamp.getUTCDate() === Number(match[3]) &&
    timestamp.getUTCHours() === Number(match[4]) &&
    timestamp.getUTCMinutes() === Number(match[5]) &&
    timestamp.getUTCSeconds() === Number(match[6])
  )
}

function isServiceDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return false
  }
  const parsed = Date.parse(`${value}T00:00:00Z`)
  return Number.isFinite(parsed) && new Date(parsed).toISOString().slice(0, 10) === value
}

function isVehicleCategory(value: unknown): value is VehicleCategory | null {
  return value === null || VEHICLE_CATEGORIES.includes(value as VehicleCategory)
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string'
}

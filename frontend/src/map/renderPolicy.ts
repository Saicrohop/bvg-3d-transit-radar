import type { EstimatedVehiclePosition } from '../realtime/vehiclePositions'
import type { CalibrationVehicleType } from './scenegraphCalibration'

export const MAX_MODELS = 250
export const MODEL_MIN_ZOOM = 12.5
export const MAX_LABELS = 100
export const LABEL_MIN_ZOOM = 14.5

export type RenderViewport = Readonly<{
  zoom: number
  west: number
  east: number
  south: number
  north: number
}>

type RenderVehicle = Pick<EstimatedVehiclePosition,
  'trip_id' | 'longitude' | 'latitude' | 'vehicle_category' | 'route_short_name'>

function containsLongitude(longitude: number, west: number, east: number): boolean {
  const span = east - west
  if (span >= 360) return true
  // Classify equivalent worlds without changing the authoritative coordinate.
  const wrappedSpan = ((span % 360) + 360) % 360
  const offset = (((longitude - west) % 360) + 360) % 360
  return offset <= wrappedSpan
}

export function planVehicleRendering<T extends RenderVehicle>(
  vehicles: readonly T[],
  viewport: RenderViewport | null,
  failedVehicleTypes: ReadonlySet<CalibrationVehicleType> = new Set(),
): { models: T[]; points: T[]; labels: T[] } {
  if (viewport === null) return { models: [], points: [], labels: [] }
  const visible = vehicles.filter((vehicle) =>
    containsLongitude(vehicle.longitude, viewport.west, viewport.east) &&
    vehicle.latitude >= viewport.south && vehicle.latitude <= viewport.north,
  ).sort((a, b) => a.trip_id < b.trip_id ? -1 : a.trip_id > b.trip_id ? 1 : 0)
  const models = viewport.zoom < MODEL_MIN_ZOOM ? [] : visible.filter((vehicle) => {
    const category = vehicle.vehicle_category
    const modelType = category === 's_bahn' ? 'train' : category
    return modelType !== null && !failedVehicleTypes.has(modelType)
  }).slice(0, MAX_MODELS)
  const modeled = new Set(models)
  const labels = viewport.zoom < LABEL_MIN_ZOOM ? [] : visible.filter((vehicle) =>
    vehicle.vehicle_category !== null && Boolean(vehicle.route_short_name?.trim()),
  ).slice(0, MAX_LABELS)
  return { models, points: visible.filter((vehicle) => !modeled.has(vehicle)), labels }
}

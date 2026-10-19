export type CalibrationVehicleType = 'bus' | 'u_bahn' | 'train' | 'tram' | 'regional'

export type ScenegraphVehicle = Readonly<{
  latitude: number
  longitude: number
  heading: number
  vehicleType: CalibrationVehicleType
}>

export type ScenegraphCalibrationVehicle = ScenegraphVehicle &
  Readonly<{
  trip_id: string
  route_short_name: string
}>

export const MODEL_URLS: Readonly<Record<CalibrationVehicleType, string>> = {
  bus: '/models/lowpoly/bvg_bus_lowpoly_v3.glb',
  u_bahn: '/models/lowpoly/u_bahn_lowpoly_v2.glb',
  train: '/models/lowpoly/s_bahn_lowpoly_v1.glb',
  tram: '/models/lowpoly/bvg_tram_lowpoly_v1.glb',
  regional: '/models/lowpoly/regional_lowpoly_v2.glb',
}

// CPU-verified source frame: +Y up, declared front +Z; map frame is ENU.
// This is a mathematical calibration, not visual confirmation of the front.
const MODEL_YAW_OFFSETS: Readonly<Record<CalibrationVehicleType, number>> = {
  bus: 180,
  u_bahn: 180,
  train: 180,
  tram: 180,
  regional: 180,
}

const MODEL_ROLL_OFFSETS: Readonly<Record<CalibrationVehicleType, number>> = {
  bus: 90,
  u_bahn: 90,
  train: 90,
  tram: 90,
  regional: 90,
}

export const MODEL_SIZE_SCALES: Readonly<
  Record<CalibrationVehicleType, number>
> = {
  bus: 1,
  u_bahn: 1,
  train: 1,
  tram: 1,
  regional: 1,
}

const MODEL_TRANSLATIONS: Readonly<
  Record<CalibrationVehicleType, readonly [number, number, number]>
> = {
  bus: [0, 0, 0],
  u_bahn: [0, 0, 0],
  train: [0, 0, 0],
  tram: [0, 0, 0],
  regional: [0, 0, 0],
}

export const MODEL_HEIGHTS_METERS: Readonly<Record<CalibrationVehicleType, number>> = {
  bus: 3.2,
  u_bahn: 3.5,
  train: 3.6,
  tram: 3.4,
  regional: 4.6,
}

export const MOCK_CALIBRATION_VEHICLES: readonly ScenegraphCalibrationVehicle[] = [
  {
    trip_id: 'bus_1',
    route_short_name: '100',
    latitude: 52.52,
    longitude: 13.405,
    heading: 0,
    vehicleType: 'bus',
  },
  {
    trip_id: 'train_1',
    route_short_name: 'S41',
    latitude: 52.521,
    longitude: 13.406,
    heading: 90,
    vehicleType: 'train',
  },
  {
    trip_id: 'bus_2',
    route_short_name: 'TXL',
    latitude: 52.519,
    longitude: 13.404,
    heading: 180,
    vehicleType: 'bus',
  },
]

export function getCalibrationModelUrl(
  vehicle: ScenegraphVehicle,
): string {
  return MODEL_URLS[vehicle.vehicleType]
}

export function getScenegraphOrientation(
  vehicle: ScenegraphVehicle,
): [number, number, number] {
  return [
    0,
    MODEL_YAW_OFFSETS[vehicle.vehicleType] - vehicle.heading,
    MODEL_ROLL_OFFSETS[vehicle.vehicleType],
  ]
}

export function getScenegraphPosition(
  vehicle: ScenegraphVehicle,
): [number, number, number] {
  return [vehicle.longitude, vehicle.latitude, 0]
}

export function getScenegraphSizeScale(
  vehicle: ScenegraphVehicle,
): number {
  return MODEL_SIZE_SCALES[vehicle.vehicleType]
}

export function getScenegraphTranslation(
  vehicle: ScenegraphVehicle,
): readonly [number, number, number] {
  return MODEL_TRANSLATIONS[vehicle.vehicleType]
}

export type CalibrationVehicleType = 'bus' | 'train' | 'tram' | 'regional'

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
  bus: '/models/bvg_bus.glb',
  train: '/models/s_bahn_db.glb',
  tram: '/models/bvg_tram.glb',
  regional: '/models/regional_bahn.glb',
}

const MODEL_YAW_OFFSETS: Readonly<Record<CalibrationVehicleType, number>> = {
  bus: 90,
  train: 180,
  tram: 90,
  regional: 90,
}

const MODEL_ROLL_OFFSETS: Readonly<Record<CalibrationVehicleType, number>> = {
  bus: 90,
  train: 90,
  tram: 90,
  regional: 90,
}

export const MODEL_SIZE_SCALES: Readonly<
  Record<CalibrationVehicleType, number>
> = {
  bus: 20,
  train: 0.75,
  tram: 22,
  regional: 9,
}

const MODEL_TRANSLATIONS: Readonly<
  Record<CalibrationVehicleType, readonly [number, number, number]>
> = {
  bus: [0, 0, 6.293897],
  train: [0, 0, 0],
  tram: [0, 0, 1.3463450148701668],
  regional: [0, 0, 2.0698822885751724],
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

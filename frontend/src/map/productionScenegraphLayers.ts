import { ScenegraphLayer } from '@deck.gl/mesh-layers'

import type {
  EstimatedVehiclePosition,
  VehicleCategory,
} from '../realtime/vehiclePositions'
import {
  getScenegraphOrientation,
  getScenegraphPosition,
  getScenegraphTranslation,
  MODEL_SIZE_SCALES,
  MODEL_URLS,
  type CalibrationVehicleType,
} from './scenegraphCalibration'

export type ProductionScenegraphVehicle = EstimatedVehiclePosition &
  Readonly<{
    heading: number
    vehicleType: CalibrationVehicleType
  }>

export type ScenegraphAssetErrorHandler = (
  vehicleType: CalibrationVehicleType,
  error: Error,
) => void

export type ProductionScenegraphLayerOptions = Readonly<{
  failedVehicleTypes?: ReadonlySet<CalibrationVehicleType>
  onScenegraphAssetError?: ScenegraphAssetErrorHandler
}>

const EMPTY_FAILED_VEHICLE_TYPES: ReadonlySet<CalibrationVehicleType> = new Set()

const MODEL_TYPE_BY_CATEGORY: Readonly<
  Record<VehicleCategory, CalibrationVehicleType>
> = {
  bus: 'bus',
  s_bahn: 'train',
  tram: 'bus',
  u_bahn: 'bus',
}

export function createProductionScenegraphLayers(
  vehicles: readonly EstimatedVehiclePosition[],
  {
    failedVehicleTypes = EMPTY_FAILED_VEHICLE_TYPES,
    onScenegraphAssetError,
  }: ProductionScenegraphLayerOptions = {},
) {
  const scenegraphVehicles = vehicles.flatMap(toProductionScenegraphVehicle)
  const genericVehicles = scenegraphVehicles.filter(
    (vehicle) => vehicle.vehicleType === 'bus',
  )
  const sBahnVehicles = scenegraphVehicles.filter(
    (vehicle) => vehicle.vehicleType === 'train',
  )
  const layers: Array<ScenegraphLayer<ProductionScenegraphVehicle>> = []

  if (!failedVehicleTypes.has('bus')) {
    layers.push(
      new ScenegraphLayer<ProductionScenegraphVehicle>({
        id: 'estimated-generic-vehicles-3d',
        data: genericVehicles,
        scenegraph: MODEL_URLS.bus,
        getPosition: getScenegraphPosition,
        getOrientation: getScenegraphOrientation,
        getTranslation: getScenegraphTranslation,
        sizeScale: MODEL_SIZE_SCALES.bus,
        sizeMaxPixels: 220,
        pickable: true,
        _lighting: 'pbr',
        onError: getScenegraphErrorHandler(
          onScenegraphAssetError,
          'bus',
        ),
      }),
    )
  }

  if (!failedVehicleTypes.has('train')) {
    layers.push(
      new ScenegraphLayer<ProductionScenegraphVehicle>({
        id: 'estimated-s-bahn-3d',
        data: sBahnVehicles,
        scenegraph: MODEL_URLS.train,
        getPosition: getScenegraphPosition,
        getOrientation: getScenegraphOrientation,
        getTranslation: getScenegraphTranslation,
        sizeScale: MODEL_SIZE_SCALES.train,
        sizeMaxPixels: 220,
        pickable: true,
        _lighting: 'pbr',
        onError: getScenegraphErrorHandler(
          onScenegraphAssetError,
          'train',
        ),
      }),
    )
  }

  return layers
}

export function getProductionScenegraphFallbackVehicles(
  vehicles: readonly EstimatedVehiclePosition[],
  failedVehicleTypes: ReadonlySet<CalibrationVehicleType> =
    EMPTY_FAILED_VEHICLE_TYPES,
): readonly EstimatedVehiclePosition[] {
  return vehicles.filter((vehicle) => {
    const vehicleType = getProductionScenegraphVehicleType(vehicle)
    return vehicleType === null || failedVehicleTypes.has(vehicleType)
  })
}

function toProductionScenegraphVehicle(
  vehicle: EstimatedVehiclePosition,
): ProductionScenegraphVehicle[] {
  const vehicleType = getProductionScenegraphVehicleType(vehicle)
  if (vehicleType === null) {
    return []
  }

  return [
    {
      ...vehicle,
      heading: vehicle.bearing_degrees,
      vehicleType,
    },
  ]
}

function getProductionScenegraphVehicleType(
  vehicle: EstimatedVehiclePosition,
): CalibrationVehicleType | null {
  if (vehicle.vehicle_category === null) {
    return null
  }

  return MODEL_TYPE_BY_CATEGORY[vehicle.vehicle_category]
}

function getScenegraphErrorHandler(
  onScenegraphAssetError: ScenegraphAssetErrorHandler | undefined,
  vehicleType: CalibrationVehicleType,
) {
  if (onScenegraphAssetError === undefined) {
    return undefined
  }

  return (error: Error) => {
    onScenegraphAssetError(vehicleType, error)
    return true
  }
}

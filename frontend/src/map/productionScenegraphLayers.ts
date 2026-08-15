import { TextLayer } from '@deck.gl/layers'
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
const VEHICLE_POSITION_TRANSITION = { getPosition: 1000 } as const
const LABEL_COLOR = [255, 255, 255] as const
const LABEL_OUTLINE_COLOR = [0, 0, 0, 255] as const
const LABEL_ELEVATION_BY_VEHICLE_TYPE: Readonly<
  Record<CalibrationVehicleType, number>
> = {
  bus: 15,
  regional: 6,
  train: 2,
  tram: 5,
}

const MODEL_TYPE_BY_CATEGORY: Readonly<
  Record<VehicleCategory, CalibrationVehicleType>
> = {
  bus: 'bus',
  regional: 'regional',
  s_bahn: 'train',
  tram: 'tram',
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
  const tramVehicles = scenegraphVehicles.filter(
    (vehicle) => vehicle.vehicleType === 'tram',
  )
  const regionalVehicles = scenegraphVehicles.filter(
    (vehicle) => vehicle.vehicleType === 'regional',
  )
  const labelVehicles = scenegraphVehicles.filter(hasValidRouteShortName)
  const layers: Array<
    | ScenegraphLayer<ProductionScenegraphVehicle>
    | TextLayer<ProductionScenegraphVehicle>
  > = []

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
        transitions: VEHICLE_POSITION_TRANSITION,
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
        transitions: VEHICLE_POSITION_TRANSITION,
        pickable: true,
        _lighting: 'pbr',
        onError: getScenegraphErrorHandler(
          onScenegraphAssetError,
          'train',
        ),
      }),
    )
  }

  if (!failedVehicleTypes.has('tram')) {
    layers.push(
      new ScenegraphLayer<ProductionScenegraphVehicle>({
        id: 'estimated-trams-3d',
        data: tramVehicles,
        scenegraph: MODEL_URLS.tram,
        getPosition: getScenegraphPosition,
        getOrientation: getScenegraphOrientation,
        getTranslation: getScenegraphTranslation,
        sizeScale: MODEL_SIZE_SCALES.tram,
        sizeMaxPixels: 220,
        transitions: VEHICLE_POSITION_TRANSITION,
        pickable: true,
        _lighting: 'pbr',
        onError: getScenegraphErrorHandler(
          onScenegraphAssetError,
          'tram',
        ),
      }),
    )
  }

  if (!failedVehicleTypes.has('regional')) {
    layers.push(
      new ScenegraphLayer<ProductionScenegraphVehicle>({
        id: 'estimated-regional-3d',
        data: regionalVehicles,
        scenegraph: MODEL_URLS.regional,
        getPosition: getScenegraphPosition,
        getOrientation: getScenegraphOrientation,
        getTranslation: getScenegraphTranslation,
        sizeScale: MODEL_SIZE_SCALES.regional,
        sizeMaxPixels: 220,
        transitions: VEHICLE_POSITION_TRANSITION,
        pickable: true,
        _lighting: 'pbr',
        onError: getScenegraphErrorHandler(
          onScenegraphAssetError,
          'regional',
        ),
      }),
    )
  }

  layers.push(
    new TextLayer<ProductionScenegraphVehicle>({
      id: 'vehicle-labels',
      data: labelVehicles,
      getPosition: getVehicleLabelPosition,
      getText: (vehicle) => vehicle.route_short_name ?? '',
      getSize: 16,
      getColor: LABEL_COLOR,
      billboard: true,
      getTextAnchor: 'middle',
      getAlignmentBaseline: 'bottom',
      fontSettings: {
        sdf: true,
        fontSize: 64,
        buffer: 4,
      },
      outlineWidth: 2,
      outlineColor: LABEL_OUTLINE_COLOR,
      parameters: {
        depthWriteEnabled: false,
        depthCompare: 'always',
      },
      transitions: VEHICLE_POSITION_TRANSITION,
      pickable: false,
    }),
  )

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

function hasValidRouteShortName(
  vehicle: ProductionScenegraphVehicle,
): boolean {
  return (
    vehicle.route_short_name !== null &&
    vehicle.route_short_name.trim().length > 0
  )
}

function getVehicleLabelPosition(
  vehicle: ProductionScenegraphVehicle,
): [number, number, number] {
  return [
    vehicle.longitude,
    vehicle.latitude,
    LABEL_ELEVATION_BY_VEHICLE_TYPE[vehicle.vehicleType],
  ]
}

import { TextLayer } from '@deck.gl/layers'
import { VertexColorScenegraphLayer as ScenegraphLayer } from './vertexColorScenegraphLayer'

import type {
  EstimatedVehiclePosition,
  VehicleCategory,
} from '../realtime/vehiclePositions'
import { getBerlinTransitLineColorRgb } from '../ui/berlinTransitColors'
import {
  getScenegraphOrientation,
  getScenegraphPosition,
  getScenegraphTranslation,
  MODEL_HEIGHTS_METERS,
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
  labelVehicles?: readonly EstimatedVehiclePosition[]
}>

const EMPTY_FAILED_VEHICLE_TYPES: ReadonlySet<CalibrationVehicleType> = new Set()
const VEHICLE_POSITION_TRANSITION = { getPosition: 1000 } as const
const LABEL_OUTLINE_COLOR = [0, 0, 0, 255] as const
const LABEL_CLEARANCE_METERS = 2

const MODEL_TYPE_BY_CATEGORY: Readonly<
  Record<VehicleCategory, CalibrationVehicleType>
> = {
  bus: 'bus',
  regional: 'regional',
  s_bahn: 'train',
  tram: 'tram',
  u_bahn: 'u_bahn',
}

export function createProductionScenegraphLayers(
  vehicles: readonly EstimatedVehiclePosition[],
  {
    failedVehicleTypes = EMPTY_FAILED_VEHICLE_TYPES,
    onScenegraphAssetError,
    labelVehicles: labelSource = vehicles,
  }: ProductionScenegraphLayerOptions = {},
) {
  const scenegraphVehicles = vehicles.flatMap(toProductionScenegraphVehicle)
  const busVehicles = scenegraphVehicles.filter(
    (vehicle) => vehicle.vehicleType === 'bus',
  )
  const uBahnVehicles = scenegraphVehicles.filter(
    (vehicle) => vehicle.vehicleType === 'u_bahn',
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
  const labelVehicles = labelSource.flatMap(toProductionScenegraphVehicle).filter(hasValidRouteShortName)
  const layers: Array<
    | ScenegraphLayer<ProductionScenegraphVehicle>
    | TextLayer<ProductionScenegraphVehicle>
  > = []

  if (busVehicles.length > 0 && !failedVehicleTypes.has('bus')) {
    layers.push(
      new ScenegraphLayer<ProductionScenegraphVehicle>({
        id: 'estimated-generic-vehicles-3d',
        data: busVehicles,
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

  if (uBahnVehicles.length > 0 && !failedVehicleTypes.has('u_bahn')) {
    layers.push(
      new ScenegraphLayer<ProductionScenegraphVehicle>({
        id: 'estimated-u-bahn-3d',
        data: uBahnVehicles,
        scenegraph: MODEL_URLS.u_bahn,
        getPosition: getScenegraphPosition,
        getOrientation: getScenegraphOrientation,
        getTranslation: getScenegraphTranslation,
        sizeScale: MODEL_SIZE_SCALES.u_bahn,
        sizeMaxPixels: 220,
        transitions: VEHICLE_POSITION_TRANSITION,
        pickable: true,
        _lighting: 'pbr',
        onError: getScenegraphErrorHandler(onScenegraphAssetError, 'u_bahn'),
      }),
    )
  }

  if (sBahnVehicles.length > 0 && !failedVehicleTypes.has('train')) {
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

  if (tramVehicles.length > 0 && !failedVehicleTypes.has('tram')) {
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

  if (regionalVehicles.length > 0 && !failedVehicleTypes.has('regional')) {
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

  if (labelVehicles.length > 0) layers.push(
    new TextLayer<ProductionScenegraphVehicle>({
      id: 'vehicle-labels',
      data: labelVehicles,
      getPosition: getVehicleLabelPosition,
      getText: (vehicle) => vehicle.route_short_name ?? '',
      getSize: 16,
      getColor: (vehicle) =>
        getBerlinTransitLineColorRgb(
          vehicle.route_short_name,
          vehicle.vehicle_category,
        ),
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
    MODEL_HEIGHTS_METERS[vehicle.vehicleType] * MODEL_SIZE_SCALES[vehicle.vehicleType] + LABEL_CLEARANCE_METERS,
  ]
}

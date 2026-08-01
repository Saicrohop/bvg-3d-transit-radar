import { TextLayer } from '@deck.gl/layers'
import { ScenegraphLayer } from '@deck.gl/mesh-layers'

import {
  getScenegraphOrientation,
  getScenegraphPosition,
  getScenegraphTranslation,
  MODEL_SIZE_SCALES,
  MODEL_URLS,
  type ScenegraphCalibrationVehicle,
} from './scenegraphCalibration'

export function createScenegraphCalibrationLayers(
  vehicles: readonly ScenegraphCalibrationVehicle[],
) {
  const buses = vehicles.filter((vehicle) => vehicle.vehicleType === 'bus')
  const trains = vehicles.filter((vehicle) => vehicle.vehicleType === 'train')

  return [
    new ScenegraphLayer<ScenegraphCalibrationVehicle>({
      id: 'mock-buses-3d',
      data: buses,
      scenegraph: MODEL_URLS.bus,
      getPosition: getScenegraphPosition,
      getOrientation: getScenegraphOrientation,
      getTranslation: getScenegraphTranslation,
      sizeScale: MODEL_SIZE_SCALES.bus,
      sizeMaxPixels: 220,
      pickable: true,
      _lighting: 'pbr',
    }),
    new ScenegraphLayer<ScenegraphCalibrationVehicle>({
      id: 'mock-trains-3d',
      data: trains,
      scenegraph: MODEL_URLS.train,
      getPosition: getScenegraphPosition,
      getOrientation: getScenegraphOrientation,
      getTranslation: getScenegraphTranslation,
      sizeScale: MODEL_SIZE_SCALES.train,
      sizeMaxPixels: 220,
      pickable: true,
      _lighting: 'pbr',
    }),
    new TextLayer<ScenegraphCalibrationVehicle>({
      id: 'mock-heading-labels',
      data: vehicles,
      getPosition: getScenegraphPosition,
      getText: (vehicle) => `${vehicle.route_short_name} · ${vehicle.heading}°`,
      getColor: [224, 235, 245],
      getSize: 13,
      sizeUnits: 'pixels',
      getTextAnchor: 'middle',
      getAlignmentBaseline: 'bottom',
      getPixelOffset: [0, -22],
      billboard: true,
    }),
  ]
}

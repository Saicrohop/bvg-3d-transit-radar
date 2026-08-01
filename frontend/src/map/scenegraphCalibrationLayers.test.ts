import { ScenegraphLayer } from '@deck.gl/mesh-layers'
import { describe, expect, it } from 'vitest'

import {
  MOCK_CALIBRATION_VEHICLES,
  type ScenegraphCalibrationVehicle,
} from './scenegraphCalibration'
import { createScenegraphCalibrationLayers } from './scenegraphCalibrationLayers'

function getOrientationFromScenegraphLayer(
  layer: ScenegraphLayer<ScenegraphCalibrationVehicle> | undefined,
  vehicle: ScenegraphCalibrationVehicle,
) {
  const getOrientation = layer?.props.getOrientation

  if (typeof getOrientation !== 'function') {
    throw new Error('Expected a ScenegraphLayer orientation accessor')
  }

  const getVehicleOrientation = getOrientation as (
    vehicle: ScenegraphCalibrationVehicle,
  ) => readonly [number, number, number]

  return getVehicleOrientation(vehicle)
}

describe('createScenegraphCalibrationLayers', () => {
  it('groups mock vehicles by type and creates cardinal-heading labels', () => {
    const layers = createScenegraphCalibrationLayers(MOCK_CALIBRATION_VEHICLES)
    const busLayer = layers.find((layer) => layer.id === 'mock-buses-3d')
    const trainLayer = layers.find((layer) => layer.id === 'mock-trains-3d')
    const labelLayer = layers.find((layer) => layer.id === 'mock-heading-labels')

    expect(busLayer?.id).toBe('mock-buses-3d')
    expect(busLayer?.props.data).toEqual([
      MOCK_CALIBRATION_VEHICLES[0],
      MOCK_CALIBRATION_VEHICLES[2],
    ])
    expect(trainLayer?.id).toBe('mock-trains-3d')
    expect(trainLayer?.props.data).toEqual([MOCK_CALIBRATION_VEHICLES[1]])
    expect(labelLayer?.props.data).toEqual(MOCK_CALIBRATION_VEHICLES)
  })

  it('passes each mock orientation accessor into the Deck scenegraph layers', () => {
    const [northboundBus, eastboundTrain, southboundBus] =
      MOCK_CALIBRATION_VEHICLES
    const layers = createScenegraphCalibrationLayers(MOCK_CALIBRATION_VEHICLES)
    const scenegraphLayers = layers.filter(
      (layer): layer is ScenegraphLayer<ScenegraphCalibrationVehicle> =>
        layer instanceof ScenegraphLayer,
    )
    const busLayer = scenegraphLayers.find(
      (layer) => layer.id === 'mock-buses-3d',
    )
    const trainLayer = scenegraphLayers.find(
      (layer) => layer.id === 'mock-trains-3d',
    )

    expect(getOrientationFromScenegraphLayer(busLayer, northboundBus)).toEqual([
      0,
      90,
      0,
    ])
    expect(getOrientationFromScenegraphLayer(busLayer, southboundBus)).toEqual([
      0,
      -90,
      0,
    ])
    expect(getOrientationFromScenegraphLayer(trainLayer, eastboundTrain)).toEqual([
      0,
      90,
      90,
    ])
  })
})

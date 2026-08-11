import { describe, expect, it } from 'vitest'

import {
  getCalibrationModelUrl,
  getScenegraphOrientation,
  getScenegraphPosition,
  getScenegraphSizeScale,
  getScenegraphTranslation,
  MOCK_CALIBRATION_VEHICLES,
} from './scenegraphCalibration'

describe('scenegraph calibration fixtures', () => {
  it('provides the requested cardinal-heading mock vehicles', () => {
    expect(MOCK_CALIBRATION_VEHICLES).toMatchObject([
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
    ])
  })

  it('selects a local model and applies the asset-specific Euler correction', () => {
    const [northboundBus, eastboundTrain, southboundBus] =
      MOCK_CALIBRATION_VEHICLES

    expect(getCalibrationModelUrl(northboundBus)).toBe('/models/bvg_bus.glb')
    expect(getCalibrationModelUrl(eastboundTrain)).toBe('/models/s_bahn_db.glb')
    expect(getScenegraphOrientation(northboundBus)).toEqual([0, 90, 90])
    expect(getScenegraphOrientation(eastboundTrain)).toEqual([0, 90, 90])
    expect(getScenegraphOrientation(southboundBus)).toEqual([0, -90, 90])
    expect(getScenegraphPosition(northboundBus)).toEqual([13.405, 52.52, 0])
    expect(getScenegraphSizeScale(northboundBus)).toBe(20)
    expect(getScenegraphSizeScale(eastboundTrain)).toBe(0.75)
    expect(getScenegraphTranslation(northboundBus)).toEqual([0, 0, 6.293897])
    expect(getScenegraphTranslation(eastboundTrain)).toEqual([0, 0, 0])
  })
})

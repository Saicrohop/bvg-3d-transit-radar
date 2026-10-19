import { describe, expect, it } from 'vitest'
import { createEstimatedVehiclePosition } from '../test/estimatedVehiclePositionFixture'
import { createLiteVehicleData, LITE_VEHICLE_LAYER, LITE_VEHICLE_SOURCE } from './liteVehicleLayer'

describe('MapLibre Lite vehicle layer', () => {
  it('builds one feature per accepted trip without retaining full telemetry records', () => {
    const vehicle = createEstimatedVehiclePosition()
    const result = createLiteVehicleData([vehicle])
    expect(result).toEqual({ type: 'FeatureCollection', features: [{
      type: 'Feature', id: vehicle.trip_id,
      geometry: { type: 'Point', coordinates: [vehicle.longitude, vehicle.latitude] },
      properties: {
        trip_id: vehicle.trip_id,
        category: 's_bahn',
        route_short_name: 'S41',
        route_color: '#ad5937',
      },
    }] })
    expect(vehicle).not.toHaveProperty('geometry')
    expect(createLiteVehicleData([]).features).toEqual([])
  })

  it('uses per-line colors on native Lite circles without Deck or GLB dependencies', () => {
    expect(LITE_VEHICLE_LAYER.type).toBe('circle')
    expect(LITE_VEHICLE_LAYER.source).toBe(LITE_VEHICLE_SOURCE)
    expect(LITE_VEHICLE_LAYER.paint?.['circle-color']).toEqual([
      'get',
      'route_color',
    ])
    expect(JSON.stringify(LITE_VEHICLE_LAYER)).not.toContain('.glb')
  })
})

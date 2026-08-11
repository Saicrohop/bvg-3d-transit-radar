import { ScenegraphLayer } from '@deck.gl/mesh-layers'
import { describe, expect, it } from 'vitest'

import type { EstimatedVehiclePosition } from '../realtime/vehiclePositions'
import {
  createProductionScenegraphLayers,
  type ProductionScenegraphVehicle,
} from './productionScenegraphLayers'

const estimatedVehicles: readonly EstimatedVehiclePosition[] = [
  {
    type: 'vehicle_position',
    source: 'trip_update_interpolation',
    is_estimated: true,
    vehicle_category: 's_bahn',
    trip_id: 's41-trip',
    route_id: 's41-route',
    longitude: 13.405,
    latitude: 52.52,
    bearing_degrees: 90,
    speed_mps: 10,
  },
  {
    type: 'vehicle_position',
    source: 'trip_update_interpolation',
    is_estimated: true,
    vehicle_category: 'u_bahn',
    trip_id: 'u2-trip',
    route_id: 'u2-route',
    longitude: 13.406,
    latitude: 52.521,
    bearing_degrees: 0,
    speed_mps: 8,
  },
  {
    type: 'vehicle_position',
    source: 'trip_update_interpolation',
    is_estimated: true,
    vehicle_category: 'bus',
    trip_id: '100-trip',
    route_id: '100-route',
    longitude: 13.407,
    latitude: 52.522,
    bearing_degrees: 180,
    speed_mps: 7,
  },
  {
    type: 'vehicle_position',
    source: 'trip_update_interpolation',
    is_estimated: true,
    vehicle_category: 'tram',
    trip_id: 'm4-trip',
    route_id: 'm4-route',
    longitude: 13.408,
    latitude: 52.523,
    bearing_degrees: 270,
    speed_mps: 9,
  },
  {
    type: 'vehicle_position',
    source: 'trip_update_interpolation',
    is_estimated: true,
    vehicle_category: null,
    trip_id: 'unknown-trip',
    route_id: 'unknown-route',
    longitude: 13.409,
    latitude: 52.524,
    bearing_degrees: 45,
    speed_mps: 5,
  },
]

function getOrientationFromScenegraphLayer(
  layer: ScenegraphLayer<ProductionScenegraphVehicle> | undefined,
  vehicle: ProductionScenegraphVehicle,
) {
  const getOrientation = layer?.props.getOrientation

  if (typeof getOrientation !== 'function') {
    throw new Error('Expected a ScenegraphLayer orientation accessor')
  }

  return (
    getOrientation as (
      currentVehicle: ProductionScenegraphVehicle,
    ) => readonly [number, number, number]
  )(vehicle)
}

function getScenegraphUrl(
  layer: ScenegraphLayer<ProductionScenegraphVehicle> | undefined,
) {
  const props = layer?.props as Record<PropertyKey, unknown> | undefined
  if (props === undefined) {
    return undefined
  }

  const originalAsyncProps = Object.getOwnPropertySymbols(props)
    .map((symbol) => props[symbol])
    .find(
      (value): value is Readonly<{ scenegraph?: unknown }> =>
        typeof value === 'object' && value !== null && 'scenegraph' in value,
    )

  return originalAsyncProps?.scenegraph
}

function getLayerData(
  layer: ScenegraphLayer<ProductionScenegraphVehicle> | undefined,
): readonly ProductionScenegraphVehicle[] {
  const data = layer?.props.data
  if (!Array.isArray(data)) {
    throw new Error('Expected the production ScenegraphLayer data to be an array')
  }

  return data as readonly ProductionScenegraphVehicle[]
}

describe('createProductionScenegraphLayers', () => {
  it('maps enriched bus, tram, and U-Bahn categories onto the calibrated BVG model', () => {
    const layers = createProductionScenegraphLayers(estimatedVehicles)
    const genericLayer = layers.find(
      (layer) => layer.id === 'estimated-generic-vehicles-3d',
    ) as ScenegraphLayer<ProductionScenegraphVehicle> | undefined
    const genericVehicles = getLayerData(genericLayer)

    expect(getScenegraphUrl(genericLayer)).toBe('/models/bvg_bus.glb')
    expect(genericLayer?.props.sizeScale).toBe(20)
    expect(genericLayer?.props._lighting).toBe('pbr')
    expect(genericLayer?.props.transitions).toEqual({ getPosition: 1000 })
    expect(genericVehicles.map((vehicle) => vehicle.trip_id)).toEqual([
      'u2-trip',
      '100-trip',
      'm4-trip',
    ])

    const u2 = genericVehicles[0]
    const route100 = genericVehicles[1]

    if (u2 === undefined || route100 === undefined) {
      throw new Error('Expected categorized production vehicles')
    }

    expect(getOrientationFromScenegraphLayer(genericLayer, u2)).toEqual([
      0,
      90,
      90,
    ])
    expect(getOrientationFromScenegraphLayer(genericLayer, route100)).toEqual([
      0,
      -90,
      90,
    ])
    expect(genericVehicles.map((vehicle) => vehicle.trip_id)).not.toContain(
      'unknown-trip',
    )
  })

  it('renders enriched S-Bahn events with the calibrated red and cream DB GLB', () => {
    const layers = createProductionScenegraphLayers(estimatedVehicles)
    const sBahnLayer = layers.find(
      (layer) => layer.id === 'estimated-s-bahn-3d',
    ) as ScenegraphLayer<ProductionScenegraphVehicle> | undefined

    expect(sBahnLayer).toBeInstanceOf(ScenegraphLayer)
    expect(getScenegraphUrl(sBahnLayer)).toBe('/models/s_bahn_db.glb')
    expect(sBahnLayer?.props.sizeScale).toBe(0.75)
    expect(sBahnLayer?.props._lighting).toBe('pbr')
    expect(sBahnLayer?.props.transitions).toEqual({ getPosition: 1000 })

    const sBahnVehicles = sBahnLayer?.props.data as
      | readonly ProductionScenegraphVehicle[]
      | undefined
    const s41 = sBahnVehicles?.[0]

    if (s41 === undefined) {
      throw new Error('Expected a configured S-Bahn ScenegraphLayer')
    }

    expect(getLayerData(sBahnLayer).map((vehicle) => vehicle.trip_id)).toEqual([
      's41-trip',
    ])
    expect(getOrientationFromScenegraphLayer(sBahnLayer, s41)).toEqual([
      0,
      90,
      90,
    ])
  })
})

import { TextLayer } from '@deck.gl/layers'
import { ScenegraphLayer } from '@deck.gl/mesh-layers'
import { describe, expect, it } from 'vitest'

import type { EstimatedVehiclePosition } from '../realtime/vehiclePositions'
import {
  createProductionScenegraphLayers,
  getProductionScenegraphFallbackVehicles,
  type ProductionScenegraphVehicle,
} from './productionScenegraphLayers'

const estimatedVehicles: readonly EstimatedVehiclePosition[] = [
  {
    type: 'vehicle_position',
    source: 'trip_update_interpolation',
    is_estimated: true,
    position_status: 'estimated_from_trip_update',
    timing_source: 'schedule_only',
    delay_seconds: null,
    feed_timestamp: null,
    trip_update_timestamp: null,
    service_date: '2026-07-19',
    entity_id: 'test-entity',
    shape_id: 'test-shape',
    previous_stop_id: 'test-stop-a',
    next_stop_id: 'test-stop-b',
    estimated_next_arrival: '2026-07-19T12:02:00Z',
    observed_at: '2026-07-19T12:00:00Z',
    vehicle_category: 's_bahn',
    trip_id: 's41-trip',
    route_id: 's41-route',
    route_short_name: 'S41',
    longitude: 13.405,
    latitude: 52.52,
    bearing_degrees: 90,
    speed_mps: 10,
  },
  {
    type: 'vehicle_position',
    source: 'trip_update_interpolation',
    is_estimated: true,
    position_status: 'estimated_from_trip_update',
    timing_source: 'schedule_only',
    delay_seconds: null,
    feed_timestamp: null,
    trip_update_timestamp: null,
    service_date: '2026-07-19',
    entity_id: 'test-entity',
    shape_id: 'test-shape',
    previous_stop_id: 'test-stop-a',
    next_stop_id: 'test-stop-b',
    estimated_next_arrival: '2026-07-19T12:02:00Z',
    observed_at: '2026-07-19T12:00:00Z',
    vehicle_category: 'u_bahn',
    trip_id: 'u2-trip',
    route_id: 'u2-route',
    route_short_name: 'U2',
    longitude: 13.406,
    latitude: 52.521,
    bearing_degrees: 0,
    speed_mps: 8,
  },
  {
    type: 'vehicle_position',
    source: 'trip_update_interpolation',
    is_estimated: true,
    position_status: 'estimated_from_trip_update',
    timing_source: 'schedule_only',
    delay_seconds: null,
    feed_timestamp: null,
    trip_update_timestamp: null,
    service_date: '2026-07-19',
    entity_id: 'test-entity',
    shape_id: 'test-shape',
    previous_stop_id: 'test-stop-a',
    next_stop_id: 'test-stop-b',
    estimated_next_arrival: '2026-07-19T12:02:00Z',
    observed_at: '2026-07-19T12:00:00Z',
    vehicle_category: 'bus',
    trip_id: '100-trip',
    route_id: '100-route',
    route_short_name: '100',
    longitude: 13.407,
    latitude: 52.522,
    bearing_degrees: 180,
    speed_mps: 7,
  },
  {
    type: 'vehicle_position',
    source: 'trip_update_interpolation',
    is_estimated: true,
    position_status: 'estimated_from_trip_update',
    timing_source: 'schedule_only',
    delay_seconds: null,
    feed_timestamp: null,
    trip_update_timestamp: null,
    service_date: '2026-07-19',
    entity_id: 'test-entity',
    shape_id: 'test-shape',
    previous_stop_id: 'test-stop-a',
    next_stop_id: 'test-stop-b',
    estimated_next_arrival: '2026-07-19T12:02:00Z',
    observed_at: '2026-07-19T12:00:00Z',
    vehicle_category: 'tram',
    trip_id: 'm4-trip',
    route_id: 'm4-route',
    route_short_name: 'M4',
    longitude: 13.408,
    latitude: 52.523,
    bearing_degrees: 270,
    speed_mps: 9,
  },
  {
    type: 'vehicle_position',
    source: 'trip_update_interpolation',
    is_estimated: true,
    position_status: 'estimated_from_trip_update',
    timing_source: 'schedule_only',
    delay_seconds: null,
    feed_timestamp: null,
    trip_update_timestamp: null,
    service_date: '2026-07-19',
    entity_id: 'test-entity',
    shape_id: 'test-shape',
    previous_stop_id: 'test-stop-a',
    next_stop_id: 'test-stop-b',
    estimated_next_arrival: '2026-07-19T12:02:00Z',
    observed_at: '2026-07-19T12:00:00Z',
    vehicle_category: 'regional',
    trip_id: 'fex-trip',
    route_id: 'fex-route',
    route_short_name: 'FEX',
    longitude: 13.409,
    latitude: 52.524,
    bearing_degrees: 45,
    speed_mps: 12,
  },
  {
    type: 'vehicle_position',
    source: 'trip_update_interpolation',
    is_estimated: true,
    position_status: 'estimated_from_trip_update',
    timing_source: 'schedule_only',
    delay_seconds: null,
    feed_timestamp: null,
    trip_update_timestamp: null,
    service_date: '2026-07-19',
    entity_id: 'test-entity',
    shape_id: 'test-shape',
    previous_stop_id: 'test-stop-a',
    next_stop_id: 'test-stop-b',
    estimated_next_arrival: '2026-07-19T12:02:00Z',
    observed_at: '2026-07-19T12:00:00Z',
    vehicle_category: null,
    trip_id: 'unknown-trip',
    route_id: 'unknown-route',
    route_short_name: null,
    longitude: 13.41,
    latitude: 52.525,
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
  it('accepts an independently budgeted label set without instantiating models for those point trips', () => {
    const layers = createProductionScenegraphLayers([estimatedVehicles[0]!], {
      labelVehicles: [estimatedVehicles[3]!],
    })
    expect(layers.map((layer) => layer.id)).toEqual(['estimated-s-bahn-3d', 'vehicle-labels'])
    expect(layers.find((layer) => layer.id === 'vehicle-labels')?.props.data)
      .toEqual([expect.objectContaining({ trip_id: 'm4-trip', vehicleType: 'tram' })])
    expect(createProductionScenegraphLayers([estimatedVehicles[0]!], { labelVehicles: [] })
      .map((layer) => layer.id)).toEqual(['estimated-s-bahn-3d'])
  })

  it('constructs no scenegraph objects or async GLB props for empty categories', () => {
    expect(createProductionScenegraphLayers([])).toEqual([])
    const layers = createProductionScenegraphLayers([estimatedVehicles[0]!])
    expect(layers.filter((layer) => layer instanceof ScenegraphLayer).map((layer) => layer.id))
      .toEqual(['estimated-s-bahn-3d'])
    expect(layers.every((layer) => (layer.props.data as unknown[]).length > 0)).toBe(true)
  })

  it('maps only bus trips onto the versioned bus model, not U-Bahn trips', () => {
    const layers = createProductionScenegraphLayers(estimatedVehicles)
    const genericLayer = layers.find(
      (layer) => layer.id === 'estimated-generic-vehicles-3d',
    ) as ScenegraphLayer<ProductionScenegraphVehicle> | undefined
    const genericVehicles = getLayerData(genericLayer)

    expect(getScenegraphUrl(genericLayer)).toBe('/models/lowpoly/bvg_bus_lowpoly_v3.glb')
    expect(genericLayer?.props.sizeScale).toBe(1)
    expect(genericLayer?.props._lighting).toBe('pbr')
    expect(genericLayer?.props.transitions).toEqual({ getPosition: 1000 })
    expect(genericVehicles.map((vehicle) => vehicle.trip_id)).toEqual([
      '100-trip',
    ])

    const route100 = genericVehicles[0]

    if (route100 === undefined) {
      throw new Error('Expected categorized production vehicles')
    }

    expect(getOrientationFromScenegraphLayer(genericLayer, route100)).toEqual([
      0,
      0,
      90,
    ])
    expect(genericVehicles.map((vehicle) => vehicle.trip_id)).not.toContain(
      'unknown-trip',
    )
  })

  it('renders tram events in their own calibrated tram ScenegraphLayer', () => {
    const layers = createProductionScenegraphLayers(estimatedVehicles)
    const tramLayer = layers.find(
      (layer) => layer.id === 'estimated-trams-3d',
    ) as ScenegraphLayer<ProductionScenegraphVehicle> | undefined
    const trams = getLayerData(tramLayer)
    const m4 = trams[0]

    expect(tramLayer).toBeInstanceOf(ScenegraphLayer)
    expect(getScenegraphUrl(tramLayer)).toBe('/models/lowpoly/bvg_tram_lowpoly_v1.glb')
    expect(tramLayer?.props.sizeScale).toBe(1)
    expect(tramLayer?.props._lighting).toBe('pbr')
    expect(tramLayer?.props.transitions).toEqual({ getPosition: 1000 })
    expect(trams.map((vehicle) => vehicle.trip_id)).toEqual(['m4-trip'])

    if (m4 === undefined) {
      throw new Error('Expected a configured tram ScenegraphLayer')
    }

    expect(getOrientationFromScenegraphLayer(tramLayer, m4)).toEqual([
      0,
      -90,
      90,
    ])
  })

  it('renders enriched S-Bahn events with the calibrated red and cream DB GLB', () => {
    const layers = createProductionScenegraphLayers(estimatedVehicles)
    const sBahnLayer = layers.find(
      (layer) => layer.id === 'estimated-s-bahn-3d',
    ) as ScenegraphLayer<ProductionScenegraphVehicle> | undefined

    expect(sBahnLayer).toBeInstanceOf(ScenegraphLayer)
    expect(getScenegraphUrl(sBahnLayer)).toBe('/models/lowpoly/s_bahn_lowpoly_v1.glb')
    expect(sBahnLayer?.props.sizeScale).toBe(1)
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

  it('renders only explicitly classified regional events in 3D and preserves unknown fallback', () => {
    const layers = createProductionScenegraphLayers(estimatedVehicles)
    const regionalLayer = layers.find(
      (layer) => layer.id === 'estimated-regional-3d',
    ) as ScenegraphLayer<ProductionScenegraphVehicle> | undefined
    const regionalVehicles = getLayerData(regionalLayer)
    const fex = regionalVehicles[0]

    expect(regionalLayer).toBeInstanceOf(ScenegraphLayer)
    expect(getScenegraphUrl(regionalLayer)).toBe('/models/lowpoly/regional_lowpoly_v2.glb')
    expect(regionalLayer?.props.sizeScale).toBe(1)
    expect(regionalLayer?.props._lighting).toBe('pbr')
    expect(regionalLayer?.props.transitions).toEqual({ getPosition: 1000 })
    expect(regionalVehicles.map((vehicle) => vehicle.trip_id)).toEqual([
      'fex-trip',
    ])

    if (fex === undefined) {
      throw new Error('Expected a configured Regional ScenegraphLayer')
    }

    expect(getOrientationFromScenegraphLayer(regionalLayer, fex)).toEqual([
      0,
      135,
      90,
    ])
    expect(
      getProductionScenegraphFallbackVehicles(estimatedVehicles).map(
        (vehicle) => vehicle.trip_id,
      ),
    ).toEqual(['unknown-trip'])
    expect(
      getProductionScenegraphFallbackVehicles(
        estimatedVehicles,
        new Set(['regional']),
      ).map((vehicle) => vehicle.trip_id),
    ).toEqual(['fex-trip', 'unknown-trip'])
  })

  it('adds billboard line labels only for instantiated vehicles with a valid public name', () => {
    const blankLabelVehicle: EstimatedVehiclePosition = {
      ...estimatedVehicles[2]!,
      trip_id: 'blank-label-trip',
      route_short_name: '   ',
    }
    const missingLabelVehicle: EstimatedVehiclePosition = {
      ...estimatedVehicles[2]!,
      trip_id: 'missing-label-trip',
      route_short_name: null,
    }
    const layers = createProductionScenegraphLayers([
      ...estimatedVehicles,
      blankLabelVehicle,
      missingLabelVehicle,
    ])
    const labelLayer = layers.find(
      (layer) => layer.id === 'vehicle-labels',
    ) as TextLayer<ProductionScenegraphVehicle> | undefined
    const data = labelLayer?.props.data

    expect(labelLayer).toBeInstanceOf(TextLayer)
    expect(Array.isArray(data)).toBe(true)
    expect(
      (data as readonly ProductionScenegraphVehicle[]).map(
        (vehicle) => vehicle.trip_id,
      ),
    ).toEqual(['s41-trip', 'u2-trip', '100-trip', 'm4-trip', 'fex-trip'])
    expect(labelLayer?.props.billboard).toBe(true)
    expect(labelLayer?.props.getSize).toBe(16)
    expect(typeof labelLayer?.props.getColor).toBe('function')
    expect(labelLayer?.props.transitions).toEqual({ getPosition: 1000 })

    const fex = (data as readonly ProductionScenegraphVehicle[]).find(
      (vehicle) => vehicle.trip_id === 'fex-trip',
    )
    const s41 = (data as readonly ProductionScenegraphVehicle[]).find(
      (vehicle) => vehicle.trip_id === 's41-trip',
    )
    const u2 = (data as readonly ProductionScenegraphVehicle[]).find(
      (vehicle) => vehicle.trip_id === 'u2-trip',
    )
    const m4 = (data as readonly ProductionScenegraphVehicle[]).find(
      (vehicle) => vehicle.trip_id === 'm4-trip',
    )
    const getPosition = labelLayer?.props.getPosition
    const getText = labelLayer?.props.getText
    const getColor = labelLayer?.props.getColor
    if (
      fex === undefined ||
      s41 === undefined ||
      u2 === undefined ||
      m4 === undefined ||
      typeof getPosition !== 'function' ||
      typeof getText !== 'function' ||
      typeof getColor !== 'function'
    ) {
      throw new Error('Expected configured TextLayer accessors')
    }

    expect(
      (
        getPosition as unknown as (
          vehicle: ProductionScenegraphVehicle,
        ) => number[]
      )(fex),
    ).toEqual([13.409, 52.524, 6.6])
    expect(
      (
        getPosition as unknown as (
          vehicle: ProductionScenegraphVehicle,
        ) => number[]
      )(s41),
    ).toEqual([13.405, 52.52, 5.6])
    expect(
      (
        getPosition as unknown as (
          vehicle: ProductionScenegraphVehicle,
        ) => number[]
      )(u2),
    ).toEqual([13.406, 52.521, 5.5])
    expect(
      (
        getPosition as unknown as (
          vehicle: ProductionScenegraphVehicle,
        ) => number[]
      )(m4),
    ).toEqual([13.408, 52.523, 5.4])
    expect((getText as (vehicle: ProductionScenegraphVehicle) => string)(fex)).toBe(
      'FEX',
    )
    const getLineRgb = getColor as unknown as (
      vehicle: ProductionScenegraphVehicle,
    ) => readonly number[]
    expect(getLineRgb(s41)).toEqual([173, 89, 55])
    expect(getLineRgb(u2)).toEqual([218, 66, 30])
    expect(getLineRgb(m4)).toEqual([255, 150, 124])
  })
})

// @vitest-environment node
import { readFileSync } from 'node:fs'
import { ScenegraphLayer } from '@deck.gl/mesh-layers'
import { describe, expect, it, vi } from 'vitest'

import { createEstimatedVehiclePosition } from '../test/estimatedVehiclePositionFixture'
import { createProductionScenegraphLayers, getProductionScenegraphFallbackVehicles } from './productionScenegraphLayers'
import { planVehicleRendering } from './renderPolicy'

const cases = [
  { category: 'bus', modelType: 'bus', id: 'estimated-generic-vehicles-3d', filename: 'bvg_bus_lowpoly_v3.glb' },
  { category: 'u_bahn', modelType: 'u_bahn', id: 'estimated-u-bahn-3d', filename: 'u_bahn_lowpoly_v2.glb' },
  { category: 's_bahn', modelType: 'train', id: 'estimated-s-bahn-3d', filename: 's_bahn_lowpoly_v1.glb' },
  { category: 'tram', modelType: 'tram', id: 'estimated-trams-3d', filename: 'bvg_tram_lowpoly_v1.glb' },
  { category: 'regional', modelType: 'regional', id: 'estimated-regional-3d', filename: 'regional_lowpoly_v2.glb' },
] as const
const vehicles = [
  ...cases.map(({ category }) => createEstimatedVehiclePosition({ trip_id: category, vehicle_category: category })),
  createEstimatedVehiclePosition({ trip_id: 'unknown', vehicle_category: null }),
]
const viewport = { zoom: 14.5, west: 13, east: 14, south: 52, north: 53 }

function originalScenegraphUrl(layer: ScenegraphLayer): unknown {
  const props = layer.props as Record<PropertyKey, unknown>
  for (const symbol of Object.getOwnPropertySymbols(props)) {
    const value = props[symbol]
    if (typeof value === 'object' && value !== null && 'scenegraph' in value) return value.scenegraph
  }
  throw new Error('Expected original async scenegraph URL')
}

describe('approved low-poly production routing', () => {
  it.each(cases)('anchors $category labels two metres above the actual model roof', (item) => {
    const raw = readFileSync(new URL(`../../public/models/lowpoly/${item.filename}`, import.meta.url))
    const jsonLength = raw.readUInt32LE(12)
    const gltf = JSON.parse(raw.subarray(20, 20 + jsonLength).toString('utf8'))
    const positionAccessor = gltf.meshes[0].primitives[0].attributes.POSITION
    const roofHeight = gltf.accessors[positionAccessor].max[1]
    const labels = createProductionScenegraphLayers(vehicles).find((layer) => layer.id === 'vehicle-labels')
    if (labels === undefined || !Array.isArray(labels.props.data) || typeof labels.props.getPosition !== 'function') {
      throw new Error('Expected label data and position accessor')
    }
    const labelVehicle = labels.props.data.find((v) => v.trip_id === item.category)
    const getPosition = labels.props.getPosition as unknown as (v: unknown) => readonly number[]
    expect(labelVehicle).toBeDefined()
    expect(getPosition(labelVehicle)[2]).toBeCloseTo(roofHeight + 2, 5)
  })

  it.each(cases)('isolates the approved $category model and its load-error key', (item) => {
    const onScenegraphAssetError = vi.fn()
    const layers = createProductionScenegraphLayers(vehicles, { onScenegraphAssetError })
    const layer = layers.find((current) => current.id === item.id)
    expect(layer).toBeInstanceOf(ScenegraphLayer)
    if (!(layer instanceof ScenegraphLayer)) throw new Error('Expected category-specific scenegraph')
    expect(originalScenegraphUrl(layer)).toBe(`/models/lowpoly/${item.filename}`)
    expect(layer.props.data).toEqual([expect.objectContaining({ trip_id: item.category, vehicleType: item.modelType })])
    expect(layer.props.sizeScale).toBe(1)
    expect(layer.props._lighting).toBe('pbr')
    const error = new Error('synthetic asset failure; no resource was requested')
    expect(layer.props.onError?.(error)).toBe(true)
    expect(onScenegraphAssetError).toHaveBeenCalledExactlyOnceWith(item.modelType, error)
  })

  it.each(cases)('keeps only failed $category trips as points in both policy and factory', (item) => {
    const failed = new Set([item.modelType])
    const plan = planVehicleRendering(vehicles, viewport, failed)
    const expectedPoints = [item.category, 'unknown'].sort()
    expect(plan.points.map((v) => v.trip_id)).toEqual(expectedPoints)
    expect(getProductionScenegraphFallbackVehicles(vehicles, failed).map((v) => v.trip_id).sort()).toEqual(expectedPoints)
    const layers = createProductionScenegraphLayers(plan.models, { failedVehicleTypes: failed, labelVehicles: [] })
    expect(layers.map((layer) => layer.id)).not.toContain(item.id)
    const modeledIds = layers.flatMap((layer) => (layer.props.data as typeof vehicles).map((v) => v.trip_id)).sort()
    expect(modeledIds).toEqual(cases.filter((v) => v.category !== item.category).map((v) => v.category).sort())
    expect(new Set([...modeledIds, ...expectedPoints]).size).toBe(vehicles.length)
  })
})

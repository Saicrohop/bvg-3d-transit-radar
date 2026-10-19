// @vitest-environment node
import { readFileSync } from 'node:fs'
import { MATRIX_ATTRIBUTES } from '../../node_modules/@deck.gl/mesh-layers/dist/utils/matrix.js'
import { describe, expect, it } from 'vitest'

import {
  getCalibrationModelUrl,
  getScenegraphOrientation,
  getScenegraphSizeScale,
  getScenegraphTranslation,
  type ScenegraphVehicle,
} from './scenegraphCalibration'

const models = [
  { vehicleType: 'bus', filename: 'bvg_bus_lowpoly_v3.glb', dimensions: [12, 2.55, 3.2] },
  { vehicleType: 'u_bahn', filename: 'u_bahn_lowpoly_v2.glb', dimensions: [30, 2.65, 3.5] },
  { vehicleType: 'train', filename: 's_bahn_lowpoly_v1.glb', dimensions: [36, 3, 3.6] },
  { vehicleType: 'tram', filename: 'bvg_tram_lowpoly_v1.glb', dimensions: [30, 2.4, 3.4] },
  { vehicleType: 'regional', filename: 'regional_lowpoly_v2.glb', dimensions: [40, 2.8, 4.6] },
] as const

function vehicle(vehicleType: ScenegraphVehicle['vehicleType'], heading = 0): ScenegraphVehicle {
  return { latitude: 52.52, longitude: 13.405, heading, vehicleType }
}

// Exercise the installed Deck CPU updater, not a renderer or graphics device.
function instanceMatrix(item: ScenegraphVehicle): Float32Array {
  const attribute = { value: new Float32Array(12), size: 12, constant: false }
  MATRIX_ATTRIBUTES.update.call({
    props: {
      data: [item], getOrientation: getScenegraphOrientation,
      getScale: [1, 1, 1], getTranslation: getScenegraphTranslation,
      getTransformMatrix: [],
    },
  }, attribute, { startRow: 0, endRow: 1 })
  return attribute.value
}

function rotate(matrix: Float32Array, point: readonly number[]): number[] {
  return [0, 1, 2].map((axis) =>
    matrix[axis] * point[0] + matrix[axis + 3] * point[1] + matrix[axis + 6] * point[2])
}

describe('approved low-poly source-frame calibration', () => {
  it.each(models)('adopts the approved version of $vehicleType in real metres', (model) => {
    const item = vehicle(model.vehicleType)
    expect(getCalibrationModelUrl(item)).toBe(`/models/lowpoly/${model.filename}`)
    expect(getScenegraphSizeScale(item)).toBe(1)
    expect(getScenegraphTranslation(item)).toEqual([0, 0, 0])
  })

  it.each(models.flatMap((model) => [0, 90, 180, 270, 37].map((heading) => ({ ...model, heading }))))(
    'maps declared +Z front and +Y up for $vehicleType at heading $heading using installed Deck matrices',
    (model) => {
      const item = vehicle(model.vehicleType, model.heading)
      expect(getScenegraphTranslation(item)).toBeDefined()
      const matrix = instanceMatrix(item)
      const forward = rotate(matrix, [0, 0, 1])
      const up = rotate(matrix, [0, 1, 0])
      const radians = model.heading * Math.PI / 180
      const expectedForward = [Math.sin(radians), Math.cos(radians), 0]
      for (let axis = 0; axis < 3; axis++) {
        expect(forward[axis]).toBeCloseTo(expectedForward[axis], 6)
        expect(up[axis]).toBeCloseTo(axis === 2 ? 1 : 0, 6)
      }
      expect(item.heading).toBe(model.heading)
    },
  )

  it.each(models)('grounds the exported bounds of $vehicleType without legacy scale/lift', (model) => {
    const item = vehicle(model.vehicleType)
    const url = getCalibrationModelUrl(item)
    expect(url).toBe(`/models/lowpoly/${model.filename}`)
    const raw = readFileSync(new URL(`../../public${url}`, import.meta.url))
    const jsonLength = raw.readUInt32LE(12)
    const gltf = JSON.parse(raw.subarray(20, 20 + jsonLength).toString('utf8'))
    expect(gltf.nodes).toHaveLength(1)
    expect(gltf.nodes[0]).not.toHaveProperty('matrix')
    expect(gltf.nodes[0]).not.toHaveProperty('rotation')
    const primitive = gltf.meshes[0].primitives[0]
    const bounds = gltf.accessors[primitive.attributes.POSITION] as { min: number[]; max: number[] }
    const corners: number[][] = []
    for (const x of [bounds.min[0], bounds.max[0]]) {
      for (const y of [bounds.min[1], bounds.max[1]]) {
        for (const z of [bounds.min[2], bounds.max[2]]) corners.push([x, y, z])
      }
    }
    const scale = getScenegraphSizeScale(item)
    const matrix = instanceMatrix(item)
    const transformed = corners.map((corner) => rotate(matrix, corner)
      .map((value, axis) => value * scale + matrix[9 + axis]))
    const minimum = [0, 1, 2].map((axis) => Math.min(...transformed.map((p) => p[axis])))
    const maximum = [0, 1, 2].map((axis) => Math.max(...transformed.map((p) => p[axis])))
    const [length, width, height] = model.dimensions
    expect(minimum[2]).toBeCloseTo(0, 5)
    expect(maximum[2]).toBeCloseTo(height, 5)
    expect(maximum[0] - minimum[0]).toBeCloseTo(width, 5)
    expect(maximum[1] - minimum[1]).toBeCloseTo(length, 5)
  })
})

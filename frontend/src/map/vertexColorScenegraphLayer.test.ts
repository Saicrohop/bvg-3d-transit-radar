// @vitest-environment node
import { readFileSync } from 'node:fs'
import { ScenegraphLayer } from '@deck.gl/mesh-layers'
import type { LayerContext } from '@deck.gl/core'
import type { Device } from '@luma.gl/core'
import { parsePBRMaterial } from '@luma.gl/gltf'
import { ShaderAssembler } from '@luma.gl/shadertools'
import { describe, expect, it } from 'vitest'

import { createEstimatedVehiclePosition } from '../test/estimatedVehiclePositionFixture'
import { createProductionScenegraphLayers } from './productionScenegraphLayers'
import { MOCK_CALIBRATION_VEHICLES } from './scenegraphCalibration'
import { createScenegraphCalibrationLayers } from './scenegraphCalibrationLayers'
import { VertexColorScenegraphLayer } from './vertexColorScenegraphLayer'

const cases = [
  { category: 'bus', filename: 'bvg_bus_lowpoly_v3.glb' },
  { category: 'u_bahn', filename: 'u_bahn_lowpoly_v2.glb' },
  { category: 's_bahn', filename: 's_bahn_lowpoly_v1.glb' },
  { category: 'tram', filename: 'bvg_tram_lowpoly_v1.glb' },
  { category: 'regional', filename: 'regional_lowpoly_v2.glb' },
] as const

// Only source descriptors are used: any graphics access fails immediately.
const forbiddenDevice = new Proxy({} as Device, {
  get() { throw new Error('Graphics device access forbidden in CPU source test') },
})
const platformInfo = {
  type: 'null', shaderLanguage: 'glsl', shaderLanguageVersion: 300,
  gpu: 'unknown', features: new Set(),
} as const

function getShaders(layer: ScenegraphLayer) {
  layer.context = { defaultShaderModules: [] } as unknown as LayerContext
  expect(layer.state).toBeUndefined()
  return layer.getShaders()
}

function readMaterial(filename: string) {
  const raw = readFileSync(new URL(`../../public/models/lowpoly/${filename}`, import.meta.url))
  const gltf = JSON.parse(raw.subarray(20, 20 + raw.readUInt32LE(12)).toString('utf8'))
  const primitive = gltf.meshes[0].primitives[0]
  const attributes = Object.fromEntries(Object.entries(primitive.attributes).map(
    ([name, index]) => [name, gltf.accessors[index as number]],
  ))
  return parsePBRMaterial(forbiddenDevice, gltf.materials[primitive.material], attributes, {
    useTangents: false, lights: true,
  })
}

function expectColorChain(vs: string, fs: string) {
  expect(vs, 'COLOR_0 must bind to the installed geometry attribute name').toMatch(/in\s+(?:highp\s+)?vec4\s+colors\s*;/)
  expect(vs).toMatch(/out\s+(?:highp\s+)?vec4\s+bvgVertexColor\s*;/)
  expect(vs).toMatch(/bvgVertexColor\s*=\s*colors\s*;/)
  expect(fs).toMatch(/in\s+(?:highp\s+)?vec4\s+bvgVertexColor\s*;/)
  const baseColorUse = fs.indexOf('baseColor *= bvgVertexColor;')
  expect(baseColorUse, 'vertex RGBA must affect material baseColor, not lit output').toBeGreaterThan(fs.indexOf('vec4 baseColor = pbrMaterial.baseColorFactor;'))
  expect(baseColorUse).toBeLessThan(fs.indexOf('if (baseColor.a < pbrMaterial.alphaCutoff)'))
  expect(baseColorUse).toBeLessThan(fs.indexOf('vec3 diffuseColor = baseColor.rgb'))
  expect(fs).toContain('vec3 specularColor = mix(f0, baseColor.rgb, metallic);')
  expect(fs).toContain('fragColor = vColor * pbr_filterColor(vec4(0));')
  expect(fs).not.toMatch(/fragColor\s*\*=\s*bvgVertexColor/)
}

describe('Scenegraph COLOR_0 material path (CPU source assembly only)', () => {
  it('uses the adapter class for all five simultaneous production model layers', () => {
    const layers = createProductionScenegraphLayers(cases.map(({ category }) => (
      createEstimatedVehiclePosition({ trip_id: category, vehicle_category: category })
    )), { labelVehicles: [] })
    expect(layers).toHaveLength(5)
    expect(layers.every((layer) => layer instanceof VertexColorScenegraphLayer)).toBe(true)
  })

  it('uses the same COLOR_0 material bridge for both shared calibration model URLs', () => {
    const layers = createScenegraphCalibrationLayers(MOCK_CALIBRATION_VEHICLES)
      .filter((layer) => layer instanceof ScenegraphLayer)
    expect(layers).toHaveLength(2)
    for (const layer of layers) {
      expect(layer).toBeInstanceOf(VertexColorScenegraphLayer)
      const shaders = getShaders(layer)
      const assembled = new ShaderAssembler().assembleGLSLShaderPair({
        ...shaders, platformInfo, defines: { ...shaders.defines, HAS_COLORS: true, HAS_NORMALS: true },
      })
      expectColorChain(assembled.vs, assembled.fs)
    }
  })

  it.each(cases)('feeds $category vertex RGBA into PBR before lighting in the production factory', ({ category, filename }) => {
    const layers = createProductionScenegraphLayers([
      createEstimatedVehiclePosition({ vehicle_category: category }),
    ], { labelVehicles: [] })
    expect(layers).toHaveLength(1)
    const layer = layers[0]
    expect(layer).toBeInstanceOf(ScenegraphLayer)
    if (!(layer instanceof ScenegraphLayer)) throw new Error('Expected model layer')
    const parsed = readMaterial(filename)
    expect(parsed.defines.HAS_COLORS).toBe(true)
    const shaders = getShaders(layer)
    const assembled = new ShaderAssembler().assembleGLSLShaderPair({
      ...shaders, platformInfo, defines: { ...parsed.defines, ...shaders.defines },
    })
    expectColorChain(assembled.vs, assembled.fs)
    expect(layer.state).toBeUndefined()
  })
})

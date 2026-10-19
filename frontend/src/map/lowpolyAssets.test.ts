// @vitest-environment node
import { createHash } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const approvedAssets = [
  ['bvg_bus_lowpoly_v3.glb', 'bcf56abbe7f23bf9beb7ae73178fcd2f497ae5346d3977389630d4a300cd67e0'],
  ['u_bahn_lowpoly_v2.glb', '10e9bb996bf4f80619a3a242662e87894e3d770d67cfde87e1de9ccede6a4a83'],
  ['s_bahn_lowpoly_v1.glb', '01fedeccd15580c7930e101cda616022f296cb2561e2f53d2b709981f61f381c'],
  ['bvg_tram_lowpoly_v1.glb', '15d9bc65072056ac8264ab6da8bd0851692bbb7fb11a40f8da7fc06631202848'],
  ['regional_lowpoly_v2.glb', '8be12fc234d4c6352c1d69a0beb6ca5d16eae3079c4bcaadadcbbfbc9c2f9486'],
] as const

describe('approved low-poly asset delivery', () => {
  it.each(approvedAssets)('ships %s byte-for-byte without reducing geometry', (filename, sha256) => {
    const url = new URL(`../../public/models/lowpoly/${filename}`, import.meta.url)
    expect(existsSync(url), `Missing approved model ${filename}`).toBe(true)
    expect(createHash('sha256').update(readFileSync(url)).digest('hex')).toBe(sha256)
  })
})

import { describe, expect, it } from 'vitest'

import {
  BERLIN_CENTER,
  BUILDING_EXTRUSION_LAYER,
  DARK_CARTO_STYLE_URL,
} from './mapStyle'

describe('Berlin base-map configuration', () => {
  it('uses the requested Berlin center and a dark Carto vector style', () => {
    expect(BERLIN_CENTER).toEqual([13.405, 52.52])
    expect(DARK_CARTO_STYLE_URL).toContain('dark-matter')
  })

  it('adds OpenStreetMap building data as fill extrusions', () => {
    expect(BUILDING_EXTRUSION_LAYER).toMatchObject({
      type: 'fill-extrusion',
      source: 'carto',
      'source-layer': 'building',
    })
  })
})

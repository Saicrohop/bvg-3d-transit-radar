import { describe, expect, it } from 'vitest'

import { getLayerTransitionIdentity, getPositionTransitions } from './transitionIdentity'

describe('getPositionTransitions', () => {
  it('compares each layer separately and disables label interpolation when glyph mappings change', () => {
    const vehicles = [{ trip_id: 'a', route_short_name: 'S1' }, { trip_id: 'b', route_short_name: 'U2' }]
    const moved = vehicles.map((item) => ({ ...item, longitude: 13.5 }))
    const original = getLayerTransitionIdentity('vehicle-labels', vehicles)
    expect(getLayerTransitionIdentity('vehicle-labels', moved)).toEqual(original)
    const renamed = getLayerTransitionIdentity('vehicle-labels', [vehicles[0]!, { ...vehicles[1]!, route_short_name: 'RE100' }])
    expect(getPositionTransitions(original, renamed, false)).toEqual({})
    const changedMembership = getLayerTransitionIdentity('vehicle-labels', [vehicles[1]!])
    expect(getPositionTransitions(original, changedMembership, false)).toEqual({})
    expect(getLayerTransitionIdentity('estimated-s-bahn-3d', vehicles)).toEqual(['a', 'b'])
    expect(getLayerTransitionIdentity('estimated-vehicle-points', [])).toEqual([])
  })

  it('allows 1000ms only for identical nonempty ordered IDs without reduced motion', () => {
    expect(getPositionTransitions(undefined, ['a'], false)).toEqual({})
    expect(getPositionTransitions([], [], false)).toEqual({})
    expect(getPositionTransitions(['a'], ['a'], false)).toEqual({ getPosition: 1000 })
    expect(getPositionTransitions(['a'], ['a'], true)).toEqual({})
    for (const next of [[], ['b'], ['a', 'b']]) {
      expect(getPositionTransitions(['a'], next, false)).toEqual({})
    }
    expect(getPositionTransitions(['a', 'b'], ['b', 'a'], false)).toEqual({})
  })
})

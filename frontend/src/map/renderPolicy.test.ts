import { describe, expect, it } from 'vitest'

import { planVehicleRendering } from './renderPolicy'

const viewport = { zoom: 12.6, west: 13, east: 14, south: 52, north: 53 }
const vehicle = {
  trip_id: 'b', vehicle_category: 's_bahn' as const,
  route_short_name: 'S41', longitude: 13.4, latitude: 52.5,
}

describe('planVehicleRendering', () => {
  it.each([
    [-350, -10, 13.4, true],
    [373, 374, 13.4, true],
    [170, -170, 175, true],
    [170, -170, -175, true],
    [170, -170, 13.4, false],
    [-180, 180, 13.4, true],
    [13, 14, 15, false],
  ])('classifies longitude %s..%s including wrapped worlds (%s)', (west, east, longitude, visible) => {
    const item = { ...vehicle, longitude }
    const plan = planVehicleRendering([item], { ...viewport, west, east })
    expect([...plan.models, ...plan.points]).toHaveLength(visible ? 1 : 0)
    expect(item.longitude).toBe(longitude)
  })
  it('enables at most 100 valid inbounds labels only at zoom 14.5', () => {
    const vehicles = Array.from({ length: 140 }, (_, index) => ({
      ...vehicle, trip_id: `trip-${String(139 - index).padStart(3, '0')}`,
    }))
    const invalid = [
      { ...vehicle, trip_id: 'a-blank', route_short_name: '  ' },
      { ...vehicle, trip_id: 'a-missing', route_short_name: null },
      { ...vehicle, trip_id: 'a-unknown', vehicle_category: null },
      { ...vehicle, trip_id: 'a-outside', latitude: 53.001 },
    ]
    expect(planVehicleRendering([...invalid, ...vehicles], { ...viewport, zoom: 14.49 }).labels).toEqual([])
    const plan = planVehicleRendering([...invalid, ...vehicles], { ...viewport, zoom: 14.5 })
    expect(plan.labels.map((item) => item.trip_id))
      .toEqual(vehicles.map((item) => item.trip_id).sort().slice(0, 100))
    const edge = { ...vehicle, longitude: 14, latitude: 53 }
    expect(planVehicleRendering([edge], viewport).models).toEqual([edge])
  })

  it('budgets exactly 250 visible models at zoom 12.5, with every overflow or failed trip kept as a point', () => {
    const vehicles = Array.from({ length: 260 }, (_, index) => ({
      ...vehicle, trip_id: `trip-${String(259 - index).padStart(3, '0')}`,
    }))
    const plan = planVehicleRendering([
      ...vehicles,
      { ...vehicle, trip_id: 'unknown', vehicle_category: null },
      { ...vehicle, trip_id: 'failed', vehicle_category: 'bus' as const },
      { ...vehicle, trip_id: 'outside', longitude: 14.01 },
    ], { ...viewport, zoom: 12.5 }, new Set(['bus']))
    expect(plan.models).toHaveLength(250)
    expect(plan.models.map((item) => item.trip_id)).toEqual(
      vehicles.map((item) => item.trip_id).sort().slice(0, 250),
    )
    expect(plan.points).toHaveLength(12)
    expect(plan.points.map((item) => item.trip_id)).toContain('failed')
    expect(plan.points.map((item) => item.trip_id)).toContain('unknown')
    const rendered = [...plan.models, ...plan.points].map((item) => item.trip_id)
    expect(new Set(rendered).size).toBe(262)
    expect(rendered).not.toContain('outside')
    expect(plan.labels).toEqual([])
  })

  it('uses no objects before load and only sorted visible points below model zoom', () => {
    const vehicles = Object.freeze([
      vehicle, { ...vehicle, trip_id: 'a' }, { ...vehicle, trip_id: 'outside', longitude: 15 },
    ])
    expect(planVehicleRendering(vehicles, null)).toEqual({ models: [], points: [], labels: [] })
    const plan = planVehicleRendering(vehicles, { ...viewport, zoom: 12.49 })
    expect(plan.models).toEqual([])
    expect(plan.labels).toEqual([])
    expect(plan.points.map((item) => item.trip_id)).toEqual(['a', 'b'])
    expect(vehicles.map((item) => item.trip_id)).toEqual(['b', 'a', 'outside'])
  })
})

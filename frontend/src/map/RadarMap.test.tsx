// @vitest-environment jsdom

import { act, render } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mapRuntime = vi.hoisted(() => ({
  addedLayers: [] as Array<Record<string, unknown>>,
  cameraChanges: [] as Array<Record<string, unknown>>,
  mapOptions: [] as Array<Record<string, unknown>>,
  overlays: [] as Array<{ props: Record<string, unknown> }>,
  removedMaps: 0,
  zoom: 12.6,
  bounds: { west: 13, east: 14, south: 52, north: 53 },
  boundsReads: 0,
  moveEndListeners: [] as Array<() => void>,
  delayLoad: false,
  loadListeners: [] as Array<() => void>,
}))

vi.mock('maplibre-gl', () => {
  class FakeMap {
    constructor(options: Record<string, unknown>) {
      mapRuntime.mapOptions.push(options)
    }

    addControl() {}

    getZoom() {
      return mapRuntime.zoom
    }

    getBounds() {
      mapRuntime.boundsReads += 1
      const { west, east, south, north } = mapRuntime.bounds
      return { getWest: () => west, getEast: () => east, getSouth: () => south, getNorth: () => north }
    }

    easeTo(options: Record<string, unknown>) {
      mapRuntime.cameraChanges.push(options)
      if (typeof options.zoom === 'number') mapRuntime.zoom = options.zoom
    }

    addLayer(layer: Record<string, unknown>) {
      mapRuntime.addedLayers.push(layer)
    }

    getLayer() {
      return undefined
    }

    getStyle() {
      return { layers: [{ id: 'place-label', type: 'symbol' }] }
    }

    on(event: string, listener: () => void) {
      if (event === 'moveend') mapRuntime.moveEndListeners.push(listener)
      if (event === 'load') {
        if (mapRuntime.delayLoad) mapRuntime.loadListeners.push(listener)
        else listener()
      }
    }

    remove() {
      mapRuntime.removedMaps += 1
    }
  }

  class FakeNavigationControl {}

  return {
    default: { Map: FakeMap, NavigationControl: FakeNavigationControl },
  }
})

vi.mock('@deck.gl/mapbox', () => {
  class FakeMapboxOverlay {
    props: Record<string, unknown>

    constructor(props: Record<string, unknown>) {
      this.props = props
      mapRuntime.overlays.push(this)
    }

    setProps(props: Record<string, unknown>) {
      this.props = { ...this.props, ...props }
    }
  }

  return { MapboxOverlay: FakeMapboxOverlay }
})

vi.mock('./productionScenegraphLayers', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./productionScenegraphLayers')>()
  return { ...actual, createProductionScenegraphLayers: vi.fn(actual.createProductionScenegraphLayers) }
})

import { RadarMap } from './RadarMap'
import { createProductionScenegraphLayers } from './productionScenegraphLayers'

const vehicle = {
  type: 'vehicle_position' as const,
  source: 'trip_update_interpolation' as const,
  is_estimated: true as const,
  position_status: 'estimated_from_trip_update' as const,
  timing_source: 'schedule_only' as const,
  delay_seconds: null,
  feed_timestamp: null,
  trip_update_timestamp: null,
  service_date: '2026-07-19',
  vehicle_category: 's_bahn' as const,
  trip_id: 'trip-42',
  entity_id: 'entity-42',
  shape_id: 'shape-42',
  previous_stop_id: 'stop-1',
  next_stop_id: 'stop-2',
  estimated_next_arrival: '2026-07-19T12:01:00Z',
  observed_at: '2026-07-19T12:00:00Z',
  route_id: 'route-7',
  route_short_name: 'S41',
  longitude: 13.405,
  latitude: 52.52,
  bearing_degrees: 91.5,
  speed_mps: 8.2,
}

beforeEach(() => {
  mapRuntime.addedLayers = []
  mapRuntime.cameraChanges = []
  mapRuntime.mapOptions = []
  mapRuntime.overlays = []
  mapRuntime.removedMaps = 0
  mapRuntime.zoom = 12.6
  mapRuntime.bounds = { west: 13, east: 14, south: 52, north: 53 }
  mapRuntime.boundsReads = 0
  mapRuntime.moveEndListeners = []
  vi.mocked(createProductionScenegraphLayers).mockClear()
  mapRuntime.delayLoad = false
  mapRuntime.loadListeners = []
})

describe('RadarMap', () => {
  it.each(['bus', 'u_bahn'] as const)('isolates %s asset failure from the other dedicated model', (failedCategory) => {
    const bus = { ...vehicle, trip_id: 'bus-trip', vehicle_category: 'bus' as const }
    const metro = { ...vehicle, trip_id: 'metro-trip', vehicle_category: 'u_bahn' as const }
    const rows = [bus, metro]
    const layerIds = { bus: 'estimated-generic-vehicles-3d', u_bahn: 'estimated-u-bahn-3d' }
    const view = render(<RadarMap vehicles={rows} />)
    const overlay = mapRuntime.overlays[0]
    type TestLayer = { id: string; props: { data: Array<{ trip_id: string }>; onError?: (error: Error) => boolean } }
    const layers = () => overlay.props.layers as TestLayer[]
    expect(layers().map((layer) => layer.id)).toEqual(['estimated-vehicle-points', layerIds.bus, layerIds.u_bahn])
    const onError = layers().find((layer) => layer.id === layerIds[failedCategory])?.props.onError
    expect(onError).toEqual(expect.any(Function))
    act(() => { expect(onError?.(new Error('synthetic load failure'))).toBe(true) })
    const failedTrip = failedCategory === 'bus' ? bus : metro
    const healthyTrip = failedCategory === 'bus' ? metro : bus
    expect(layers().find((layer) => layer.id === 'estimated-vehicle-points')?.props.data).toEqual([failedTrip])
    expect(layers().find((layer) => layer.id === layerIds[healthyTrip.vehicle_category])?.props.data)
      .toEqual([expect.objectContaining({ trip_id: healthyTrip.trip_id })])
    view.rerender(<RadarMap vehicles={[...rows]} />)
    expect(layers().map((layer) => layer.id)).not.toContain(layerIds[failedCategory])
    expect(mapRuntime.mapOptions).toHaveLength(1)
    view.unmount()
  })

  it('does not initialize a late 3D adapter hidden and never remounts it for visibility alone', () => {
    let visibility: DocumentVisibilityState = 'hidden'
    const getter = vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility)
    let view: ReturnType<typeof render> | null = null
    try {
      view = render(<RadarMap vehicles={[vehicle]} />)
      expect(mapRuntime.mapOptions).toHaveLength(0)
      expect(mapRuntime.overlays).toHaveLength(0)
      expect(createProductionScenegraphLayers).not.toHaveBeenCalled()
      act(() => { visibility = 'visible'; document.dispatchEvent(new Event('visibilitychange')) })
      expect(mapRuntime.mapOptions).toHaveLength(1)
      expect(mapRuntime.overlays).toHaveLength(1)
      const cameraChanges = mapRuntime.cameraChanges.length
      act(() => { visibility = 'hidden'; document.dispatchEvent(new Event('visibilitychange')) })
      act(() => { visibility = 'visible'; document.dispatchEvent(new Event('visibilitychange')) })
      expect(mapRuntime.mapOptions).toHaveLength(1)
      expect(mapRuntime.removedMaps).toBe(0)
      expect(mapRuntime.cameraChanges).toHaveLength(cameraChanges)
    } finally {
      view?.unmount()
      getter.mockRestore()
    }
    expect(mapRuntime.removedMaps).toBe(1)
  })
  it('gates transitions by each applied layer identity across sort, churn, disappearance and label edits', () => {
    mapRuntime.zoom = 14.5
    const a = { ...vehicle, trip_id: 'a' }
    const b = { ...vehicle, trip_id: 'b' }
    const bus = { ...vehicle, trip_id: 'bus', vehicle_category: 'bus' as const }
    const point = { ...vehicle, trip_id: 'unknown', vehicle_category: null }
    const view = render(<RadarMap vehicles={[b, point, bus, a]} />)
    const overlay = mapRuntime.overlays[0]
    const layers = () => overlay.props.layers as Array<{
      id: string; props: { data: Array<{ trip_id: string }>; transitions: Record<string, number> }
    }>
    const transitions = (id: string) => layers().find((layer) => layer.id === id)?.props.transitions
    expect(layers().every((layer) => Object.keys(layer.props.transitions).length === 0)).toBe(true)
    expect(layers().find((layer) => layer.id === 'estimated-s-bahn-3d')?.props.data.map((item) => item.trip_id))
      .toEqual(['a', 'b'])
    view.rerender(<RadarMap vehicles={[a, bus, b, point]} />)
    expect(layers().every((layer) => layer.props.transitions.getPosition === 1000)).toBe(true)

    const c = { ...b, trip_id: 'c' }
    view.rerender(<RadarMap vehicles={[a, bus, c, point]} />)
    expect(transitions('estimated-s-bahn-3d')).toEqual({})
    expect(transitions('vehicle-labels')).toEqual({})
    expect(transitions('estimated-generic-vehicles-3d')).toEqual({ getPosition: 1000 })
    expect(transitions('estimated-vehicle-points')).toEqual({ getPosition: 1000 })
    view.rerender(<RadarMap vehicles={[bus, point]} />)
    view.rerender(<RadarMap vehicles={[a, bus, c, point]} />)
    expect(transitions('estimated-s-bahn-3d')).toEqual({})
    view.rerender(<RadarMap vehicles={[{ ...a, route_short_name: 'RE100' }, bus, c, point]} />)
    expect(transitions('vehicle-labels')).toEqual({})
    expect(transitions('estimated-s-bahn-3d')).toEqual({ getPosition: 1000 })
    view.unmount()
  })

  it('recomputes bounded budgets on moveend and snapshot updates, never per animation frame', () => {
    const many = Array.from({ length: 260 }, (_, index) => ({
      ...vehicle, trip_id: `trip-${String(259 - index).padStart(3, '0')}`,
    }))
    const offscreen = { ...vehicle, trip_id: 'offscreen', longitude: 15 }
    const view = render(<RadarMap vehicles={[...many, offscreen]} />)
    const overlay = mapRuntime.overlays[0]
    const layers = () => overlay.props.layers as Array<{ id: string; props: { data: Array<{ trip_id: string }> } }>
    expect(layers().find((layer) => layer.id === 'estimated-s-bahn-3d')?.props.data).toHaveLength(250)
    expect(layers().find((layer) => layer.id === 'estimated-vehicle-points')?.props.data).toHaveLength(10)
    expect(layers().map((layer) => layer.id)).not.toContain('vehicle-labels')
    expect(mapRuntime.boundsReads).toBe(1)

    mapRuntime.zoom = 14.5
    act(() => mapRuntime.moveEndListeners.forEach((listener) => listener()))
    expect(layers().find((layer) => layer.id === 'vehicle-labels')?.props.data).toHaveLength(100)
    expect(mapRuntime.boundsReads).toBe(2)
    const latest = { ...vehicle, trip_id: 'latest', longitude: 15 }
    view.rerender(<RadarMap vehicles={[latest]} />)
    expect(layers().flatMap((layer) => layer.props.data)).toEqual([])
    expect(mapRuntime.boundsReads).toBe(2)

    mapRuntime.zoom = 12.49
    mapRuntime.bounds = { west: 14.5, east: 15.5, south: 52, north: 53 }
    act(() => mapRuntime.moveEndListeners.forEach((listener) => listener()))
    expect(layers().map((layer) => layer.id)).toEqual(['estimated-vehicle-points'])
    expect(layers()[0].props.data).toEqual([latest])
    expect(mapRuntime.boundsReads).toBe(3)
    view.unmount()
    act(() => mapRuntime.moveEndListeners.forEach((listener) => listener()))
    expect(mapRuntime.boundsReads).toBe(3)
  })

  it('constructs no scenegraphs before map load and caps both renderers at pixel ratio 1', () => {
    mapRuntime.delayLoad = true
    const view = render(<RadarMap vehicles={[vehicle]} />)
    view.rerender(<RadarMap vehicles={[{ ...vehicle, trip_id: 'latest-trip' }]} />)
    expect(createProductionScenegraphLayers).not.toHaveBeenCalled()
    expect(mapRuntime.boundsReads).toBe(0)
    act(() => mapRuntime.loadListeners[0]())
    expect(mapRuntime.mapOptions[0].pixelRatio).toBe(1)
    expect(mapRuntime.overlays[0].props.useDevicePixels).toBe(1)
    expect(mapRuntime.boundsReads).toBe(1)
    const layers = mapRuntime.overlays[0].props.layers as Array<{ id: string; props: { data: unknown[] } }>
    expect(layers.map((layer) => layer.id)).toEqual(['estimated-vehicle-points', 'estimated-s-bahn-3d'])
    expect(layers[1].props.data).toEqual([expect.objectContaining({ trip_id: 'latest-trip' })])
    view.unmount()
  })

  it('retains a pending 3D enable command across delayed map load', () => {
    mapRuntime.delayLoad = true
    const view = render(<RadarMap vehicles={[vehicle]} />)
    view.rerender(<RadarMap vehicles={[vehicle]} viewMode="2d" />)
    view.rerender(<RadarMap vehicles={[vehicle]} viewMode="3d" />)
    expect(mapRuntime.cameraChanges).toHaveLength(0)
    act(() => mapRuntime.loadListeners[0]())
    expect(mapRuntime.cameraChanges.at(-1)).toMatchObject({ pitch: 55, zoom: 13.5 })
    view.unmount()
  })

  it('disables position transitions through layer clones and restores them without recreating the map', () => {
    const vehicles = [vehicle]
    const view = render(<RadarMap vehicles={vehicles} />)
    const overlay = mapRuntime.overlays[0]
    type RenderedLayer = { id: string; props: Record<string, unknown> }
    const originalLayers = overlay.props.layers as RenderedLayer[]
    view.rerender(<RadarMap vehicles={vehicles} reducedMotion />)
    const reducedLayers = overlay.props.layers as RenderedLayer[]
    expect(reducedLayers.map((layer) => layer.props.transitions)).toEqual(originalLayers.map(() => ({})))
    reducedLayers.forEach((layer, index) => {
      expect(layer).not.toBe(originalLayers[index])
      expect(layer.id).toBe(originalLayers[index].id)
      for (const prop of ['data', 'getPosition', 'getOrientation', 'sizeScale', 'getTranslation', 'getColor', '_lighting']) {
        expect(layer.props[prop]).toBe(originalLayers[index].props[prop])
      }
    })
    expect(originalLayers.map((layer) => layer.props.transitions)).toEqual(originalLayers.map(() => ({})))
    view.rerender(<RadarMap vehicles={vehicles} reducedMotion={false} />)
    expect((overlay.props.layers as RenderedLayer[]).map((layer) => layer.props.transitions))
      .toEqual(originalLayers.map((layer) => (layer.props.data as unknown[]).length ? { getPosition: 1000 } : {}))
    expect(mapRuntime.mapOptions).toHaveLength(1)
    expect(mapRuntime.overlays).toEqual([overlay])
    view.unmount()
  })

  it('selects only current snapshot trips through the latest callback without recreating the map', () => {
    const onSelect = vi.fn()
    const latestOnSelect = vi.fn()
    const view = render(<RadarMap vehicles={[vehicle]} onVehicleSelect={onSelect} />)
    const overlay = mapRuntime.overlays[0]
    expect(overlay.props.onClick).toEqual(expect.any(Function))
    const click = overlay.props.onClick as (info: { object?: unknown }) => void
    const initialLayers = overlay.props.layers as Array<{
      id: string; props: { data: readonly unknown[] }
    }>
    const picked = initialLayers.find((layer) => layer.id === 'estimated-s-bahn-3d')!.props.data[0]
    act(() => click({ object: picked }))
    expect(onSelect).toHaveBeenCalledExactlyOnceWith(vehicle.trip_id)

    const currentVehicle = { ...vehicle, trip_id: 'new-trip' }
    view.rerender(<RadarMap vehicles={[currentVehicle]} onVehicleSelect={latestOnSelect} />)
    act(() => {
      for (const object of [undefined, null, {}, 'trip-42', { trip_id: 42 }, { trip_id: 'unknown' }, picked]) {
        click({ object })
      }
    })
    expect(latestOnSelect).not.toHaveBeenCalled()
    act(() => click({ object: currentVehicle }))
    expect(latestOnSelect).toHaveBeenCalledExactlyOnceWith('new-trip')
    expect(onSelect).toHaveBeenCalledTimes(1)
    view.rerender(<RadarMap vehicles={[]} onVehicleSelect={latestOnSelect} />)
    act(() => click({ object: currentVehicle }))
    expect(latestOnSelect).toHaveBeenCalledTimes(1)
    view.rerender(<RadarMap vehicles={[currentVehicle]} />)
    expect(() => click({ object: currentVehicle })).not.toThrow()
    expect(mapRuntime.mapOptions).toHaveLength(1)
    expect(mapRuntime.overlays).toEqual([overlay])
    expect(overlay.props.onClick).toBe(click)
    view.unmount()
  })

  it.each([null, { longitude: 13.8, latitude: 52.7, requestId: 2 }])(
    'applies latest pre-load data and camera state (%j)',
    (target) => {
      mapRuntime.delayLoad = true
      const view = render(<RadarMap vehicles={[vehicle]} />)
      const latestVehicle = { ...vehicle, trip_id: 'latest-trip' }
      view.rerender(<RadarMap vehicles={[latestVehicle]} viewMode="2d" cameraTarget={target} reducedMotion />)
      expect(mapRuntime.overlays).toHaveLength(0)
      expect(mapRuntime.cameraChanges).toHaveLength(0)
      act(() => mapRuntime.loadListeners[0]())
      const layers = mapRuntime.overlays[0].props.layers as Array<{
        id: string; props: { data: readonly { trip_id: string }[] }
      }>
      expect(layers.find((layer) => layer.id === 'estimated-s-bahn-3d')?.props.data)
        .toEqual([expect.objectContaining({ trip_id: 'latest-trip' })])
      expect(mapRuntime.cameraChanges.at(-1)).toMatchObject({ pitch: 0, duration: 0 })
      if (target) {
        expect(mapRuntime.cameraChanges.at(-1)).toMatchObject({ center: [13.8, 52.7], zoom: 16.5 })
      }
      expect(mapRuntime.mapOptions).toHaveLength(1)
      view.unmount()
    },
  )

  it('issues explicit camera targets once per request or coordinate change, not per snapshot', () => {
    const target = { longitude: 13.4, latitude: 52.5, requestId: 1 }
    const view = render(<RadarMap vehicles={[vehicle]} />)
    view.rerender(<RadarMap vehicles={[vehicle]} cameraTarget={target} />)
    expect(mapRuntime.cameraChanges).toEqual([
      { center: [13.4, 52.5], zoom: 16.5, pitch: 55, duration: 700 },
    ])

    view.rerender(<RadarMap vehicles={[{ ...vehicle, longitude: 13.6 }]} cameraTarget={{ ...target }} />)
    expect(mapRuntime.cameraChanges).toHaveLength(1)
    view.rerender(<RadarMap vehicles={[vehicle]} cameraTarget={{ ...target, requestId: 2 }} />)
    expect(mapRuntime.cameraChanges).toHaveLength(2)
    view.rerender(<RadarMap vehicles={[vehicle]} cameraTarget={{ ...target, requestId: 2, longitude: 13.7 }} />)
    expect(mapRuntime.cameraChanges).toHaveLength(3)
    expect(mapRuntime.cameraChanges.at(-1)).toMatchObject({ center: [13.7, 52.5] })
    view.rerender(<RadarMap vehicles={[vehicle]} viewMode="2d" cameraTarget={{ ...target, latitude: 52.6 }} reducedMotion />)
    expect(mapRuntime.cameraChanges.at(-1)).toEqual({
      center: [13.4, 52.6], zoom: 16.5, pitch: 0, duration: 0,
    })
    expect(mapRuntime.mapOptions).toHaveLength(1)
    view.unmount()
  })

  it('switches camera pitch without recreating the map and keeps 3D extrusions in zoom range', () => {
    const view = render(<RadarMap vehicles={[vehicle]} />)
    const overlay = mapRuntime.overlays[0]
    mapRuntime.cameraChanges = []

    view.rerender(<RadarMap vehicles={[vehicle]} viewMode="2d" />)
    expect(mapRuntime.cameraChanges.at(-1)).toMatchObject({ pitch: 0 })

    mapRuntime.zoom = 12
    view.rerender(<RadarMap vehicles={[vehicle]} viewMode="3d" />)
    expect(mapRuntime.cameraChanges.at(-1)).toMatchObject({ pitch: 55, zoom: 13.5 })

    view.rerender(<RadarMap vehicles={[vehicle]} viewMode="2d" />)
    mapRuntime.zoom = 17
    view.rerender(<RadarMap vehicles={[vehicle]} viewMode="3d" />)
    expect(mapRuntime.cameraChanges.at(-1)).toMatchObject({ pitch: 55, zoom: 17 })
    expect(mapRuntime.mapOptions).toHaveLength(1)
    expect(mapRuntime.overlays).toEqual([overlay])
    expect(mapRuntime.removedMaps).toBe(0)
    view.unmount()
  })

  it('renders categorized S-Bahn estimates with the calibrated red DB GLB without mock layers', () => {
    const uncategorizedVehicle = {
      ...vehicle,
      vehicle_category: null,
      trip_id: 'unknown-trip',
    }
    const view = render(
      <RadarMap vehicles={[vehicle, uncategorizedVehicle]} />,
    )

    expect(mapRuntime.mapOptions[0]).toMatchObject({
      center: [13.405, 52.52],
      pitch: 55,
    })
    expect(mapRuntime.addedLayers[0]).toMatchObject({
      type: 'fill-extrusion',
      source: 'carto',
      'source-layer': 'building',
    })
    expect(mapRuntime.overlays).toHaveLength(1)
    const overlay = mapRuntime.overlays.at(-1)
    const layers = overlay?.props.layers as Array<{
      id: string
      props: {
        data: readonly { trip_id: string }[]
        transitions?: { getPosition: number }
      }
    }>

    expect(layers.map((layer) => layer.id)).toEqual([
      'estimated-vehicle-points',
      'estimated-s-bahn-3d',
    ])
    expect(overlay?.props.effects).toHaveLength(1)
    expect(overlay?.props.interleaved).toBe(false)
    expect(overlay?.props.deviceProps).toMatchObject({
      type: 'webgl',
      createCanvasContext: { alphaMode: 'premultiplied' },
    })
    expect(overlay?.props.onDeviceInitialized).toEqual(expect.any(Function))
    expect(
      layers
        .filter((layer) =>
          [
            'estimated-generic-vehicles-3d',
            'estimated-s-bahn-3d',
            'estimated-trams-3d',
            'estimated-regional-3d',
            'vehicle-labels',
            'estimated-vehicle-points',
          ].includes(layer.id),
        )
        .map((layer) => layer.props.transitions),
    ).toEqual([{}, {}])
    expect(
      layers.find((layer) => layer.id === 'estimated-s-bahn-3d')?.props
        .data,
    ).toHaveLength(1)
    expect(
      layers.find((layer) => layer.id === 'estimated-vehicle-points')?.props.data,
    ).toEqual([uncategorizedVehicle])
    expect(layers.find((layer) => layer.id === 'vehicle-labels')).toBeUndefined()
    mapRuntime.zoom = 14.5
    act(() => mapRuntime.moveEndListeners.forEach((listener) => listener()))
    const zoomedLayers = overlay?.props.layers as typeof layers
    expect(
      zoomedLayers.find((layer) => layer.id === 'vehicle-labels')?.props.data,
    ).toEqual([
      expect.objectContaining({
        trip_id: vehicle.trip_id,
        route_short_name: vehicle.route_short_name,
      }),
    ])
    expect(layers.map((layer) => layer.id)).not.toContain('mock-trains-3d')

    view.unmount()
    expect(mapRuntime.removedMaps).toBe(1)
  })

  it('moves a vehicle to the 2D fallback when its S-Bahn icon fails to load', () => {
    const uncategorizedVehicle = {
      ...vehicle,
      vehicle_category: null,
      trip_id: 'unknown-trip',
    }
    const view = render(
      <RadarMap vehicles={[vehicle, uncategorizedVehicle]} />,
    )
    const overlay = mapRuntime.overlays.at(-1)
    const initialLayers = overlay?.props.layers as Array<{
      id: string
      props: {
        data: readonly { trip_id: string }[]
        onError?: (error: Error) => boolean
      }
    }>
    const onError = initialLayers.find(
      (layer) => layer.id === 'estimated-s-bahn-3d',
    )?.props.onError

    expect(onError).toEqual(expect.any(Function))

    act(() => {
      onError?.(new Error('loading GLB: 404 Not Found'))
    })

    const updatedLayers = overlay?.props.layers as Array<{
      id: string
      props: { data: readonly { trip_id: string }[] }
    }>

    expect(updatedLayers.map((layer) => layer.id)).not.toContain(
      'estimated-s-bahn-3d',
    )
    expect(
      updatedLayers.find((layer) => layer.id === 'estimated-vehicle-points')
        ?.props.data,
    ).toEqual([vehicle, uncategorizedVehicle])

    view.unmount()
  })
})

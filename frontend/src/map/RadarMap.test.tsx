// @vitest-environment jsdom

import { act, render } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mapRuntime = vi.hoisted(() => ({
  addedLayers: [] as Array<Record<string, unknown>>,
  cameraChanges: [] as Array<Record<string, unknown>>,
  mapOptions: [] as Array<Record<string, unknown>>,
  overlays: [] as Array<{ props: Record<string, unknown> }>,
  removedMaps: 0,
}))

vi.mock('maplibre-gl', () => {
  class FakeMap {
    constructor(options: Record<string, unknown>) {
      mapRuntime.mapOptions.push(options)
    }

    addControl() {}

    easeTo(options: Record<string, unknown>) {
      mapRuntime.cameraChanges.push(options)
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
      if (event === 'load') {
        listener()
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

import { RadarMap } from './RadarMap'

const vehicle = {
  type: 'vehicle_position' as const,
  source: 'trip_update_interpolation' as const,
  is_estimated: true as const,
  vehicle_category: 's_bahn' as const,
  trip_id: 'trip-42',
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
})

describe('RadarMap', () => {
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
      'estimated-generic-vehicles-3d',
      'estimated-s-bahn-3d',
      'estimated-trams-3d',
      'estimated-regional-3d',
      'vehicle-labels',
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
    ).toEqual([
      { getPosition: 1000 },
      { getPosition: 1000 },
      { getPosition: 1000 },
      { getPosition: 1000 },
      { getPosition: 1000 },
      { getPosition: 1000 },
    ])
    expect(
      layers.find((layer) => layer.id === 'estimated-s-bahn-3d')?.props
        .data,
    ).toHaveLength(1)
    expect(
      layers.find((layer) => layer.id === 'estimated-vehicle-points')?.props.data,
    ).toEqual([uncategorizedVehicle])
    expect(
      layers.find((layer) => layer.id === 'vehicle-labels')?.props.data,
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

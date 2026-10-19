// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createEstimatedVehiclePosition } from '../test/estimatedVehiclePositionFixture'

const runtime = vi.hoisted(() => ({
  options: [] as Record<string, unknown>[],
  listeners: new Map<string, (...args: never[]) => void>(),
  source: { setData: vi.fn() },
  addSource: vi.fn(), addLayer: vi.fn(), remove: vi.fn(), easeTo: vi.fn(),
  construct: vi.fn(), addControl: vi.fn(),
  query: vi.fn(),
}))
vi.mock('maplibre-gl', () => ({ default: {
  Map: class {
    constructor(options: Record<string, unknown>) { runtime.construct(); runtime.options.push(options) }
    addControl = runtime.addControl
    addSource = runtime.addSource
    addLayer = runtime.addLayer
    getSource() { return runtime.source }
    on(event: string, callback: (...args: never[]) => void) { runtime.listeners.set(event, callback); return this }
    remove = runtime.remove
    easeTo = runtime.easeTo
    queryRenderedFeatures = runtime.query
  }, NavigationControl: class {},
} }))
// A runtime import of Deck in Lite would fail this test before rendering.
vi.mock('@deck.gl/mapbox', () => { throw new Error('Deck must not load in Lite') })
import { MapLibreLite } from './MapLibreLite'

const vehicle = createEstimatedVehiclePosition()
beforeEach(() => { runtime.options = []; runtime.listeners.clear(); vi.resetAllMocks() })
afterEach(cleanup)

describe('MapLibre Lite lifecycle (mocked renderer)', () => {
  it('waits when a late adapter mounts hidden and preserves context-loss failure across visibility changes', () => {
    let visibility: DocumentVisibilityState = 'hidden'
    const getter = vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility)
    try {
      const view = render(<MapLibreLite vehicles={[vehicle]} />)
      expect(runtime.options).toHaveLength(0)
      act(() => { visibility = 'visible'; document.dispatchEvent(new Event('visibilitychange')) })
      expect(runtime.options).toHaveLength(1)
      act(() => runtime.listeners.get('load')?.())
      act(() => runtime.listeners.get('webglcontextlost')?.())
      expect(runtime.remove).toHaveBeenCalledTimes(1)
      act(() => { visibility = 'hidden'; document.dispatchEvent(new Event('visibilitychange')) })
      act(() => { visibility = 'visible'; document.dispatchEvent(new Event('visibilitychange')) })
      expect(runtime.options).toHaveLength(1)
      expect(screen.getByRole('alert').textContent).toContain('Contexto gráfico perdido')
      view.unmount()
      expect(runtime.remove).toHaveBeenCalledTimes(1)
    } finally {
      cleanup()
      getter.mockRestore()
    }
  })
  it.each(['construct', 'addControl'] as const)('contains early %s failure without leaking or retrying', operation => {
    runtime[operation].mockImplementationOnce(() => { throw new Error(`${operation} failed`) })
    const shellAction = vi.fn()
    const shell = (vehicles = [vehicle]) => <>
      <button onClick={shellAction}>Shell action</button>
      <MapLibreLite vehicles={vehicles} />
    </>
    const view = render(shell())
    expect(screen.getByRole('alert').textContent).toContain('Use Sem mapa')
    expect(screen.queryByLabelText('Mapa Lite de Berlim')).toBeNull()
    act(() => screen.getByRole('button', { name: 'Shell action' }).click())
    expect(shellAction).toHaveBeenCalledTimes(1)
    expect(runtime.remove).toHaveBeenCalledTimes(operation === 'construct' ? 0 : 1)
    view.rerender(shell([]))
    view.unmount()
    expect(runtime.construct).toHaveBeenCalledTimes(1)
    expect(runtime.addSource).not.toHaveBeenCalled()
    expect(runtime.remove).toHaveBeenCalledTimes(operation === 'construct' ? 0 : 1)
  })

  it.each(['addSource', 'addLayer', 'easeTo'] as const)(
    'contains asynchronous %s initialization failure and immediately retires the renderer',
    operation => {
      runtime[operation].mockImplementationOnce(() => { throw new Error(`${operation} failed`) })
      const select = vi.fn(), shellAction = vi.fn()
      const target = { longitude: 13.4, latitude: 52.5, requestId: 1 }
      const shell = (vehicles = [vehicle], requestId = 1) => <>
        <button onClick={shellAction}>Shell action</button>
        <MapLibreLite vehicles={vehicles} cameraTarget={{ ...target, requestId }} onVehicleSelect={select} />
      </>
      const view = render(shell())
      expect(() => act(() => {
        runtime.listeners.get('load')?.()
        // Disposal must happen in the callback, not wait for React cleanup.
        expect(runtime.remove).toHaveBeenCalledTimes(1)
      })).not.toThrow()
      expect(screen.getByRole('alert').textContent).toContain('Use Sem mapa')
      expect(screen.queryByLabelText('Mapa Lite de Berlim')).toBeNull()
      act(() => screen.getByRole('button', { name: 'Shell action' }).click())
      expect(shellAction).toHaveBeenCalledTimes(1)
      const initializationCalls = [runtime.addSource.mock.calls.length, runtime.addLayer.mock.calls.length, runtime.easeTo.mock.calls.length]

      view.rerender(shell([], 2))
      expect(runtime.source.setData).not.toHaveBeenCalled()
      act(() => {
        runtime.listeners.get('load')?.()
        runtime.listeners.get('click')?.(...[{ point: { x: 1, y: 2 } }] as never[])
        runtime.listeners.get('error')?.()
        runtime.listeners.get('webglcontextlost')?.()
      })
      expect([runtime.addSource.mock.calls.length, runtime.addLayer.mock.calls.length, runtime.easeTo.mock.calls.length]).toEqual(initializationCalls)
      expect(runtime.query).not.toHaveBeenCalled()
      expect(select).not.toHaveBeenCalled()
      expect(screen.queryByRole('status')).toBeNull()
      expect(screen.getByRole('alert').textContent).not.toContain('Contexto gráfico perdido')
      expect(runtime.options).toHaveLength(1)
      view.unmount()
      expect(runtime.remove).toHaveBeenCalledTimes(1)
    },
  )

  it('uses the latest pick callback and camera target but never reissues the same target for a snapshot update', () => {
    const select = vi.fn(), nextSelect = vi.fn()
    const target = { longitude: 13.4, latitude: 52.5, requestId: 1 }
    const view = render(<MapLibreLite vehicles={[vehicle]} onVehicleSelect={select} cameraTarget={target} />)
    act(() => runtime.listeners.get('load')?.())
    expect(runtime.easeTo).toHaveBeenCalledTimes(1)
    expect(runtime.easeTo.mock.lastCall?.[0]).toMatchObject({ center: [13.4, 52.5], pitch: 0 })
    runtime.query.mockReturnValue([{ properties: { trip_id: vehicle.trip_id } }])
    act(() => runtime.listeners.get('click')?.(...[{ point: { x: 1, y: 2 } }] as never[]))
    expect(select).toHaveBeenCalledWith(vehicle.trip_id)
    view.rerender(<MapLibreLite vehicles={[vehicle]} onVehicleSelect={nextSelect} cameraTarget={{ ...target }} />)
    act(() => runtime.listeners.get('click')?.(...[{ point: { x: 1, y: 2 } }] as never[]))
    expect(nextSelect).toHaveBeenCalledWith(vehicle.trip_id)
    expect(runtime.easeTo).toHaveBeenCalledTimes(1)
    view.rerender(<MapLibreLite vehicles={[]} cameraTarget={{ ...target, requestId: 2 }} reducedMotion />)
    expect(runtime.easeTo.mock.lastCall?.[0].duration).toBe(0)
    act(() => runtime.listeners.get('click')?.(...[{ point: { x: 1, y: 2 } }] as never[]))
    expect(nextSelect).toHaveBeenCalledTimes(1)
  })

  it('warns on resource failure and stops the map after context loss without losing the shell', () => {
    render(<MapLibreLite vehicles={[vehicle]} />)
    act(() => runtime.listeners.get('error')?.())
    expect(screen.getByRole('status').textContent).toContain('recursos do mapa')
    expect(runtime.remove).not.toHaveBeenCalled()
    act(() => runtime.listeners.get('webglcontextlost')?.())
    expect(screen.getByRole('alert').textContent).toContain('Contexto gráfico perdido')
    expect(runtime.remove).toHaveBeenCalledTimes(1)
    act(() => runtime.listeners.get('load')?.())
    expect(runtime.addSource).not.toHaveBeenCalled()
  })

  it('starts top-down at capped pixel ratio, applies latest authoritative data after load and releases resources', () => {
    const view = render(<MapLibreLite vehicles={[vehicle]} />)
    expect(runtime.options[0]).toMatchObject({ pitch: 0, maxPitch: 0, touchPitch: false, pixelRatio: 1 })
    const next = { ...vehicle, trip_id: 'new' }
    view.rerender(<MapLibreLite vehicles={[next]} />)
    act(() => runtime.listeners.get('load')?.())
    expect(runtime.addSource.mock.lastCall?.[1].data.features[0].id).toBe('new')
    expect(runtime.addLayer.mock.lastCall?.[0].type).toBe('circle')
    expect(runtime.addLayer.mock.calls.every(([layer]) => layer.type !== 'fill-extrusion')).toBe(true)
    view.rerender(<MapLibreLite vehicles={[]} />)
    expect(runtime.source.setData.mock.lastCall?.[0].features).toEqual([])
    expect(runtime.options).toHaveLength(1)
    view.unmount()
    expect(runtime.remove).toHaveBeenCalledTimes(1)
    act(() => runtime.listeners.get('load')?.())
    expect(runtime.addSource).toHaveBeenCalledTimes(1)
  })
})

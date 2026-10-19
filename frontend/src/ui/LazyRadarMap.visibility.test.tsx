// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { RadarMapProps } from '../map/mapTypes'
import { createEstimatedVehiclePosition } from '../test/estimatedVehiclePositionFixture'

const calls = vi.hoisted(() => ({ liteImport: vi.fn(), deckImport: vi.fn(), liteProps: vi.fn(), deckProps: vi.fn() }))
vi.mock('../map/MapLibreLite', () => {
  calls.liteImport()
  return { MapLibreLite: (props: RadarMapProps) => {
    calls.liteProps(props)
    return <output data-testid="visible-lite">{props.vehicles.map(vehicle => vehicle.trip_id).join(',')}</output>
  } }
})
vi.mock('../map/RadarMap', () => {
  calls.deckImport()
  return { RadarMap: (props: RadarMapProps) => {
    calls.deckProps(props)
    return <output data-testid="visible-3d">{props.vehicles.map(vehicle => vehicle.trip_id).join(',')}</output>
  } }
})
import { LazyRadarMap } from './LazyRadarMap'

let visibility: DocumentVisibilityState = 'visible'
function changeVisibility(next: DocumentVisibilityState) {
  act(() => { visibility = next; document.dispatchEvent(new Event('visibilitychange')) })
}
beforeEach(() => {
  visibility = 'visible'
  calls.liteProps.mockClear()
  calls.deckProps.mockClear()
  vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility)
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('does not request either renderer until the page is visible', async () => {
  visibility = 'hidden'
  const view = render(<LazyRadarMap mode="lite" vehicles={[]} />)
  expect(calls.liteImport).not.toHaveBeenCalled()
  expect(calls.deckImport).not.toHaveBeenCalled()
  view.rerender(<LazyRadarMap mode="3d" vehicles={[]} />)
  expect(calls.liteImport).not.toHaveBeenCalled()
  expect(calls.deckImport).not.toHaveBeenCalled()
  changeVisibility('visible')
  expect(await screen.findByTestId('visible-3d')).toBeTruthy()
  expect(calls.liteImport).not.toHaveBeenCalled()
})

it.each(['lite', '3d'] as const)('coalesces hidden %s updates to the latest authoritative snapshot, including empty', async mode => {
  const a = createEstimatedVehiclePosition({ trip_id: 'a' })
  const b = { ...a, trip_id: 'b' }
  const c = { ...a, trip_id: 'c' }
  const testId = mode === 'lite' ? 'visible-lite' : 'visible-3d'
  const propsCalls = mode === 'lite' ? calls.liteProps : calls.deckProps
  const view = render(<LazyRadarMap mode={mode} vehicles={[a]} />)
  expect((await screen.findByTestId(testId)).textContent).toBe('a')
  changeVisibility('hidden')
  view.rerender(<LazyRadarMap mode={mode} vehicles={[b]} />)
  view.rerender(<LazyRadarMap mode={mode} vehicles={[c]} />)
  expect(screen.getByTestId(testId).textContent).toBe('a')
  changeVisibility('visible')
  expect(screen.getByTestId(testId).textContent).toBe('c')
  expect(propsCalls.mock.calls.some(([props]) => props.vehicles[0]?.trip_id === 'b')).toBe(false)
  changeVisibility('hidden')
  view.rerender(<LazyRadarMap mode={mode} vehicles={[]} />)
  expect(screen.getByTestId(testId).textContent).toBe('c')
  changeVisibility('visible')
  expect(screen.getByTestId(testId).textContent).toBe('')
})

it('honors explicit off while hidden and never restores the old renderer on return', async () => {
  const view = render(<LazyRadarMap vehicles={[]} />)
  expect(await screen.findByTestId('visible-lite')).toBeTruthy()
  changeVisibility('hidden')
  view.rerender(<LazyRadarMap mode="off" vehicles={[]} />)
  expect(screen.queryByTestId('visible-lite')).toBeNull()
  changeVisibility('visible')
  expect(screen.queryByTestId('visible-lite')).toBeNull()
  expect(screen.getByRole('status').textContent).toContain('Mapa desligado')
})

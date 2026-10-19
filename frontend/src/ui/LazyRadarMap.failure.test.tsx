// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

vi.mock('../map/RadarMap', () => { throw new Error('synthetic chunk failure') })
vi.mock('../map/MapLibreLite', () => ({ MapLibreLite: () => <output data-testid="healthy-lite">Lite ready</output> }))
import { LazyRadarMap } from './LazyRadarMap'

afterEach(() => { cleanup(); vi.restoreAllMocks() })
it('retains an error boundary across hide/show instead of remounting a failed renderer', async () => {
  let visibility: DocumentVisibilityState = 'visible'
  vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility)
  vi.spyOn(console, 'error').mockImplementation(() => {})
  render(<LazyRadarMap mode="3d" vehicles={[]} />)
  expect(await screen.findByRole('alert')).toBeTruthy()
  act(() => { visibility = 'hidden'; document.dispatchEvent(new Event('visibilitychange')) })
  act(() => { visibility = 'visible'; document.dispatchEvent(new Event('visibilitychange')) })
  expect(screen.getByRole('alert').textContent).toContain('Cartografia indisponível')
})
it('contains a rejected 3D module and recovers by switching to Lite or no renderer', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {})
  const view = render(<><h1>Shell intact</h1><LazyRadarMap mode="3d" vehicles={[]} /></>)
  expect((await screen.findByRole('alert')).textContent).toContain('Cartografia indisponível')
  expect(screen.getByRole('heading').textContent).toBe('Shell intact')
  view.rerender(<><h1>Shell intact</h1><LazyRadarMap mode="lite" vehicles={[]} /></>)
  expect(await screen.findByTestId('healthy-lite')).toBeTruthy()
  view.rerender(<><h1>Shell intact</h1><LazyRadarMap mode="off" vehicles={[]} /></>)
  expect(screen.queryByTestId('healthy-lite')).toBeNull()
  expect(screen.getByRole('status').textContent).toContain('Mapa desligado')
})

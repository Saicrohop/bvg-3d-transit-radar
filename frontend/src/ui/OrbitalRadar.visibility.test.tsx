// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import type { RadarMapProps } from '../map/mapTypes'
import type { EstimatedVehiclePosition } from '../realtime/vehiclePositions'
import { createEstimatedVehiclePosition } from '../test/estimatedVehiclePositionFixture'

vi.mock('../map/MapLibreLite', () => ({ MapLibreLite: (props: RadarMapProps) =>
  <output data-testid="retained-map-trips">{props.vehicles.map(vehicle => vehicle.trip_id).join(',')}</output>,
}))
vi.mock('../map/RadarMap', () => { throw new Error('This panel test must not request 3D') })
import { OrbitalRadar } from './OrbitalRadar'

const a = createEstimatedVehiclePosition({ trip_id: 'a' })
const bus = createEstimatedVehiclePosition({ trip_id: 'bus', route_short_name: '100', vehicle_category: 'bus' })
function feed(vehicles: readonly EstimatedVehiclePosition[]): Parameters<typeof OrbitalRadar>[0] {
  return {
    connectionStatus: 'open', vehicles, rejectedMessages: 0, dataStatus: 'fresh', dataStatusReason: 'recent_snapshot',
    snapshot: {
      type: 'vehicle_position_snapshot', schema_version: 1,
      cycle_id: '9dd9f135-3bc0-499c-85b8-758b8d6be790',
      feed_timestamp: a.feed_timestamp, observed_at: a.observed_at, positions: vehicles,
      statistics: { trip_updates_received: vehicles.length, positions_estimated: vehicles.length, positions_suppressed: 0 },
    },
  }
}
afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('keeps authoritative panel totals, filters and inspection current while only map props wait', async () => {
  let visibility: DocumentVisibilityState = 'visible'
  vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility)
  const view = render(<OrbitalRadar {...feed([a])} />)
  expect((await screen.findByTestId('retained-map-trips')).textContent).toBe('a')
  fireEvent.click(screen.getByRole('button', { name: 'Inspecionar S41' }))
  expect(screen.getByTestId('inspector-trip').textContent).toBe('a')
  act(() => { visibility = 'hidden'; document.dispatchEvent(new Event('visibilitychange')) })
  view.rerender(<OrbitalRadar {...feed([bus])} />)
  expect(screen.getByTestId('snapshot-count').textContent).toBe('1')
  expect(screen.queryByTestId('inspector-trip')).toBeNull()
  expect(screen.getByTestId('retained-map-trips').textContent).toBe('a')
  fireEvent.click(screen.getByRole('button', { name: 'Ônibus' }))
  act(() => { visibility = 'visible'; document.dispatchEvent(new Event('visibilitychange')) })
  expect(screen.getByTestId('retained-map-trips').textContent).toBe('bus')
  expect(screen.getByRole('button', { name: 'Ônibus' }).getAttribute('aria-pressed')).toBe('true')
  act(() => { visibility = 'hidden'; document.dispatchEvent(new Event('visibilitychange')) })
  view.rerender(<OrbitalRadar {...feed([])} />)
  expect(screen.getByTestId('snapshot-count').textContent).toBe('0')
  expect(screen.getByText('Snapshot válido sem posições estimadas.')).toBeTruthy()
  expect(screen.getByText('WebSocket conectado')).toBeTruthy()
  expect(screen.getByTestId('retained-map-trips').textContent).toBe('bus')
  act(() => { visibility = 'visible'; document.dispatchEvent(new Event('visibilitychange')) })
  expect(screen.getByTestId('retained-map-trips').textContent).toBe('')
})

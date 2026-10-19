// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ realtime: vi.fn(), map: vi.fn() }))
vi.mock('./realtime/useEstimatedVehiclePositions', () => ({
  useEstimatedVehiclePositions: mocks.realtime,
}))
vi.mock('./ui/LazyRadarMap', () => ({
  LazyRadarMap: (props: { vehicles: Array<{ trip_id: string }> }) => {
    mocks.map(props)
    return <output data-testid="map-trips">{props.vehicles.map(v => v.trip_id).join(',')}</output>
  },
}))

import App from './App'
import type { SnapshotFreshnessReason, SnapshotFreshnessStatus } from './realtime/connectionPolicy'
import type { EstimatedVehiclePosition } from './realtime/vehiclePositions'

const vehicle = {
  type: 'vehicle_position' as const,
  source: 'trip_update_interpolation' as const,
  is_estimated: true as const,
  position_status: 'estimated_from_trip_update' as const,
  timing_source: 'schedule_only' as const,
  delay_seconds: null,
  feed_timestamp: '2026-09-11T08:00:00Z',
  observed_at: '2026-09-11T08:00:02Z',
  trip_update_timestamp: null,
  service_date: '2026-09-11',
  vehicle_category: 's_bahn' as const,
  entity_id: 'entity-42',
  trip_id: 'trip-42',
  route_id: 'route-7',
  route_short_name: 'S41',
  shape_id: 'shape-42',
  previous_stop_id: 'stop-A',
  next_stop_id: 'stop-B',
  estimated_next_arrival: '2026-09-11T08:03:00Z',
  longitude: 13.405,
  latitude: 52.52,
  bearing_degrees: 91.5,
  speed_mps: 8.2,
}
const bus = { ...vehicle, trip_id: 'trip-bus', route_id: 'route-bus', route_short_name: '100', vehicle_category: 'bus' as const }

function feed(
  vehicles: readonly EstimatedVehiclePosition[] = [vehicle],
  connectionStatus = 'open',
  dataStatus: SnapshotFreshnessStatus = 'fresh',
  dataStatusReason: SnapshotFreshnessReason = 'recent_snapshot',
) {
  return {
    connectionStatus, vehicles, rejectedMessages: 0, dataStatus, dataStatusReason,
    snapshot: {
      type: 'vehicle_position_snapshot', schema_version: 1,
      cycle_id: 'test-cycle', feed_timestamp: vehicle.feed_timestamp,
      observed_at: vehicle.observed_at, positions: vehicles,
      statistics: { trip_updates_received: vehicles.length + 3, positions_estimated: vehicles.length, positions_suppressed: 3 },
    },
  }
}

beforeEach(() => { mocks.realtime.mockReturnValue(feed()); mocks.map.mockClear() })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState(null, '', '/') })

describe('Orbital production radar', () => {
  it.each([['?map=off', 'off'], ['?map=3d', 'lite']])('honors map-off startup but never enables 3D from a URL (%s)', (query, mode) => {
    window.history.replaceState(null, '', `/${query}`)
    render(<App />)
    expect(mocks.map.mock.lastCall?.[0].mode).toBe(mode)
  })
  it('renders the approved Orbital shell with accepted snapshot totals and real map data', () => {
    render(<App />)
    expect(screen.getByRole('heading', { name: 'BERLIN / PULSE' })).toBeTruthy()
    expect(screen.getByText('WebSocket conectado')).toBeTruthy()
    expect(screen.getByTestId('snapshot-count').textContent).toBe('1')
    expect(screen.getByTestId('map-trips').textContent).toBe('trip-42')
    expect(screen.getByText('Estimativa por TripUpdate · não é GPS')).toBeTruthy()
    expect(screen.queryByText(/dados simulados/i)).toBeNull()
    expect(screen.queryByRole('button', { name: /calibração/i })).toBeNull()
  })

  it('defaults to Lite and preserves filters across explicit 3D and panel-only choices', () => {
    mocks.realtime.mockReturnValue(feed([vehicle, bus]))
    render(<App />)
    expect(screen.getByRole('button', { name: 'Mapa Lite' }).getAttribute('aria-pressed')).toBe('true')
    expect(mocks.map.mock.lastCall?.[0].mode).toBe('lite')
    fireEvent.click(screen.getByRole('button', { name: 'Ônibus' }))
    fireEvent.click(screen.getByRole('button', { name: 'Vista 3D opcional' }))
    expect(mocks.map.mock.lastCall?.[0].mode).toBe('3d')
    expect(mocks.map.mock.lastCall?.[0].vehicles).toEqual([bus])
    fireEvent.click(screen.getByRole('button', { name: 'Somente painéis' }))
    expect(mocks.map.mock.lastCall?.[0].mode).toBe('off')
    expect(screen.getByTestId('snapshot-count').textContent).toBe('2')
    expect(screen.getByRole('button', { name: 'Ônibus' }).getAttribute('aria-pressed')).toBe('true')
  })

  it('filters only accepted vehicles by category and line without mutating snapshot totals', () => {
    mocks.realtime.mockReturnValue(feed([vehicle, bus]))
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Ônibus' }))
    expect(screen.getByTestId('map-trips').textContent).toBe('trip-bus')
    expect(screen.getByTestId('snapshot-count').textContent).toBe('2')
    fireEvent.click(screen.getByRole('button', { name: 'Todos' }))
    fireEvent.change(screen.getByRole('searchbox', { name: 'Buscar linha ou viagem' }), { target: { value: 'S41' } })
    expect(screen.getByTestId('map-trips').textContent).toBe('trip-42')
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'not-a-line' } })
    expect(screen.getByTestId('map-trips').textContent).toBe('')
    expect(screen.getByText('Nenhuma viagem corresponde aos filtros.')).toBeTruthy()
  })

  it('inspects and locates a real trip then removes its details with the next authoritative snapshot', () => {
    const view = render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Inspecionar S41' }))
    expect(screen.getByTestId('inspector-trip').textContent).toBe('trip-42')
    expect(screen.getByText('stop-B')).toBeTruthy()
    expect(screen.getByText('Sem evidência realtime')).toBeTruthy()
    expect(screen.queryByText('0 s')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Localizar no mapa' }))
    expect(mocks.map.mock.lastCall?.[0].cameraTarget).toMatchObject({ longitude: 13.405, latitude: 52.52 })
    mocks.realtime.mockReturnValue(feed([]))
    view.rerender(<App />)
    expect(screen.getByTestId('map-trips').textContent).toBe('')
    expect(screen.queryByText('stop-B')).toBeNull()
    expect(screen.getByText('Selecione uma linha ou um veículo no mapa.')).toBeTruthy()
  })

  it('distinguishes waiting, valid empty, rejected input and disconnected retained data', () => {
    mocks.realtime.mockReturnValue({ connectionStatus: 'open', vehicles: [], snapshot: null, rejectedMessages: 0, dataStatus: 'awaiting', dataStatusReason: 'awaiting_snapshot' })
    const view = render(<App />)
    expect(screen.getByText('Aguardando o primeiro snapshot válido.')).toBeTruthy()
    expect(screen.getByTestId('snapshot-count').textContent).toBe('—')
    mocks.realtime.mockReturnValue(feed([]))
    view.rerender(<App />)
    expect(screen.getByText('Snapshot válido sem posições estimadas.')).toBeTruthy()
    mocks.realtime.mockReturnValue({ ...feed([vehicle], 'reconnecting', 'stale', 'no_recent_snapshot'), rejectedMessages: 2 })
    view.rerender(<App />)
    expect(screen.getByTestId('map-trips').textContent).toBe('trip-42')
    expect(screen.getByText(/Último snapshot preservado; reconectando automaticamente/)).toBeTruthy()
    expect(screen.getByText(/2 mensagens rejeitadas/)).toBeTruthy()
    expect(screen.getByTestId('data-status').textContent).toBe('Dados antigos')
    expect(screen.getByText('test-cycle')).toBeTruthy()
  })

  it('separates transport reconnection from stale snapshot status', () => {
    mocks.realtime.mockReturnValue(feed([vehicle], 'reconnecting', 'stale', 'old_snapshot'))
    render(<App />)
    expect(screen.getByText('Reconectando ao WebSocket')).toBeTruthy()
    expect(screen.getByTestId('data-status').textContent).toContain('Dados antigos')
    expect(screen.getByText(/não são dados ativos/)).toBeTruthy()
    expect(screen.getByTestId('snapshot-count').textContent).toBe('1')
  })

  it('provides reversible camera and panel controls while honoring system reduced motion', () => {
    let reduced = false
    let notify = () => {}
    vi.stubGlobal('matchMedia', () => ({ matches: reduced, addEventListener: (_: string, listener: () => void) => { notify = listener }, removeEventListener: vi.fn() }))
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Mapa Lite' }))
    expect(mocks.map.mock.lastCall?.[0].viewMode).toBe('2d')
    fireEvent.click(screen.getByRole('button', { name: 'Vista 3D opcional' }))
    expect(mocks.map.mock.lastCall?.[0].viewMode).toBe('3d')
    fireEvent.click(screen.getByRole('button', { name: 'Recolher painéis' }))
    expect(screen.queryByRole('complementary', { name: 'Rede de transporte' })).toBeNull()
    expect(screen.getByTestId('map-trips').textContent).toBe('trip-42')
    fireEvent.click(screen.getByRole('button', { name: 'Mostrar painéis' }))
    fireEvent.click(screen.getByRole('button', { name: 'Reduzir movimento' }))
    expect(mocks.map.mock.lastCall?.[0].reducedMotion).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Reduzir movimento' }))
    expect(mocks.map.mock.lastCall?.[0].reducedMotion).toBe(false)
    act(() => { reduced = true; notify() })
    expect(mocks.map.mock.lastCall?.[0].reducedMotion).toBe(true)
    expect((screen.getByRole('button', { name: 'Reduzir movimento' }) as HTMLButtonElement).disabled).toBe(true)
  })
})

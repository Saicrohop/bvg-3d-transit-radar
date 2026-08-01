// @vitest-environment jsdom

import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const realtime = vi.hoisted(() => ({
  useEstimatedVehiclePositions: vi.fn(),
}))

vi.mock('./realtime/useEstimatedVehiclePositions', () => realtime)
vi.mock('./map/RadarMap', () => ({
  RadarMap: ({ vehicles }: { vehicles: Array<{ vehicle_category: unknown }> }) => (
    <>
      <output data-testid="production-model-count">
        {vehicles.filter((vehicle) => vehicle.vehicle_category !== null).length}
      </output>
      <output data-testid="vehicle-point-count">{vehicles.length}</output>
    </>
  ),
}))

import App from './App'

const vehicle = {
  type: 'vehicle_position' as const,
  source: 'trip_update_interpolation' as const,
  is_estimated: true as const,
  vehicle_category: 's_bahn' as const,
  trip_id: 'trip-42',
  route_id: 'route-7',
  longitude: 13.405,
  latitude: 52.52,
  bearing_degrees: 91.5,
  speed_mps: 8.2,
}

describe('App', () => {
  it('shows the connected production model feed without loading calibration mocks', () => {
    realtime.useEstimatedVehiclePositions.mockReturnValue({
      connectionStatus: 'open',
      vehicles: [vehicle],
    })

    render(<App />)

    expect(screen.getByText('WebSocket conectado')).toBeTruthy()
    expect(screen.getByText('posição estimada ativa')).toBeTruthy()
    expect(screen.getByText('MODELOS 3D EM TEMPO REAL')).toBeTruthy()
    expect(screen.getByTestId('production-model-count').textContent).toBe('1')
    expect(screen.getByTestId('vehicle-point-count').textContent).toBe('1')
    expect(
      screen.queryByRole('button', { name: 'Ativar calibração 3D' }),
    ).toBeNull()
  })
})

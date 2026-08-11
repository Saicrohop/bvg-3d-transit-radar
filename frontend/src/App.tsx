import './App.css'

import { useMemo } from 'react'

import { RadarMap } from './map/RadarMap'
import { useEstimatedVehiclePositions } from './realtime/useEstimatedVehiclePositions'

const POSITIONS_WS_URL =
  import.meta.env.VITE_POSITIONS_WS_URL ??
  'ws://127.0.0.1:8000/ws/positions'

const CONNECTION_LABELS = {
  closed: 'WebSocket desconectado',
  connecting: 'Conectando ao WebSocket',
  error: 'Erro na conexão WebSocket',
  open: 'WebSocket conectado',
} as const

function RealtimeRadarView() {
  const { connectionStatus, vehicles } =
    useEstimatedVehiclePositions(POSITIONS_WS_URL)
  const categorizedVehicleCount = useMemo(
    () =>
      vehicles.filter((vehicle) => vehicle.vehicle_category !== null).length,
    [vehicles],
  )

  return (
    <>
      <RadarMap vehicles={vehicles} />

      <header className="radar-header">
        <div>
          <p className="eyebrow">BVG · VBB · BERLIN</p>
          <h1>Transit Radar</h1>
        </div>
        <div className="radar-header-actions">
          <div className="connection-status" data-status={connectionStatus}>
            <span aria-hidden="true" className="status-dot" />
            {CONNECTION_LABELS[connectionStatus]}
          </div>
        </div>
      </header>

      <aside className="radar-panel" aria-live="polite">
        <p className="panel-label">POSIÇÕES ATIVAS</p>
        <strong>{vehicles.length}</strong>
        <span>
          {vehicles.length === 1
            ? 'posição estimada ativa'
            : 'posições estimadas ativas'}
        </span>
        <div className="estimated-notice">
          <span className="vehicle-swatch" aria-hidden="true" />
          Estimativa por TripUpdate · não é GPS
        </div>
      </aside>

      <aside className="production-model-panel" aria-live="polite">
        <p className="panel-label">MODELOS 3D EM TEMPO REAL</p>
        <strong>{categorizedVehicleCount}</strong>
        <span>
          {categorizedVehicleCount === 1
            ? 'veículo categorizado em 3D'
            : 'veículos categorizados em 3D'}
        </span>
        <div className="estimated-notice">
          S-Bahn · U-Bahn · ônibus · tram estimados
        </div>
      </aside>

      <footer className="radar-footer">
        Modelos 3D categorizados · estimativas por TripUpdate, não GPS
      </footer>
    </>
  )
}

function App() {
  return (
    <main className="radar-shell">
      <RealtimeRadarView />
    </main>
  )
}

export default App

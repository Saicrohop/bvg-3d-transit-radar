import { useMemo, useState } from 'react'

import type { EstimatedVehiclePosition, VehicleCategory } from '../realtime/vehiclePositions'
import type { useEstimatedVehiclePositions } from '../realtime/useEstimatedVehiclePositions'
import { LazyRadarMap } from './LazyRadarMap'
import type { MapDisplayMode } from '../map/mapTypes'
import { RouteList } from './RouteList'
import { TripInspector } from './TripInspector'
import { SnapshotTelemetry } from './SnapshotTelemetry'
import { usePrefersReducedMotion } from './usePrefersReducedMotion'

const CONNECTION_LABELS = {
  closed: 'WebSocket desconectado',
  connecting: 'Conectando ao WebSocket',
  error: 'Erro na conexão WebSocket',
  open: 'WebSocket conectado',
  reconnecting: 'Reconectando ao WebSocket',
} as const

const DATA_STATUS_REASON_LABELS = {
  awaiting_snapshot: 'nenhum snapshot aceito',
  recent_snapshot: 'snapshot recebido recentemente',
  no_recent_snapshot: 'nenhum snapshot válido recebido no limite esperado',
  invalid_timestamp: 'proveniência temporal inválida',
  future_timestamp: 'proveniência temporal futura',
  old_snapshot: 'timestamps do snapshot antigos',
} as const

type OrbitalRadarProps = ReturnType<typeof useEstimatedVehiclePositions>

const CATEGORIES = [
  ['all', 'Todos'], ['u_bahn', 'U-Bahn'], ['s_bahn', 'S-Bahn'],
  ['bus', 'Ônibus'], ['tram', 'Tram'], ['regional', 'Regional'], ['unknown', 'Sem categoria'],
] as const
type CategoryFilter = VehicleCategory | 'all' | 'unknown'

export function OrbitalRadar({
  connectionStatus,
  vehicles,
  snapshot,
  rejectedMessages,
  dataStatus = 'awaiting',
  dataStatusReason = 'awaiting_snapshot',
}: OrbitalRadarProps) {
  const [mapMode, setMapMode] = useState<MapDisplayMode>(() =>
    typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('map') === 'off'
      ? 'off' : 'lite',
  )
  const [panelsHidden, setPanelsHidden] = useState(false)
  const [motionReduced, setMotionReduced] = useState(false)
  const systemReducedMotion = usePrefersReducedMotion()
  const reducedMotion = motionReduced || systemReducedMotion
  const [category, setCategory] = useState<CategoryFilter>('all')
  const [query, setQuery] = useState('')
  const [selectedTripId, setSelectedTripId] = useState<string | null>(null)
  const [cameraTarget, setCameraTarget] = useState<{ longitude: number; latitude: number; requestId: number } | null>(null)
  const visibleVehicles = useMemo(() => {
    const search = query.trim().toLocaleLowerCase()
    return vehicles.filter(vehicle =>
      (category === 'all' || (category === 'unknown' ? vehicle.vehicle_category === null : vehicle.vehicle_category === category)) &&
      [vehicle.route_short_name, vehicle.route_id, vehicle.trip_id].some(value => value?.toLocaleLowerCase().includes(search)),
    )
  }, [vehicles, category, query])
  const selectedVehicle = visibleVehicles.find(vehicle => vehicle.trip_id === selectedTripId) ?? null
  function locateVehicle(vehicle: EstimatedVehiclePosition) {
    setCameraTarget(previous => ({ longitude: vehicle.longitude, latitude: vehicle.latitude, requestId: (previous?.requestId ?? 0) + 1 }))
  }
  return (
    <main className="orbital-shell" data-reduced-motion={reducedMotion} data-panels-hidden={panelsHidden}>
      <header className="orbital-header">
        <div className="orbital-brand">
          <span className="brand-emblem" aria-hidden="true">B/P</span>
          <div><p className="eyebrow">TRANSIT RADAR · ORBITAL / 01</p><h1>BERLIN <span>/</span> PULSE</h1></div>
        </div>
        <div className="connection-status" data-status={connectionStatus} role="status">
          <span className="status-dot" aria-hidden="true" />{CONNECTION_LABELS[connectionStatus]}
        </div>
        <nav className="orbital-controls" aria-label="Visualização Orbital">
          <button aria-label="Mapa Lite" aria-pressed={mapMode === 'lite'} onClick={() => setMapMode('lite')}>LITE / 2D</button>
          <button aria-label="Vista 3D opcional" title="Carrega Deck e modelos 3D; maior uso de GPU" aria-pressed={mapMode === '3d'} onClick={() => setMapMode('3d')}>3D opcional</button>
          <button aria-label="Somente painéis" aria-pressed={mapMode === 'off'} onClick={() => setMapMode('off')}>Sem mapa</button>
          <button aria-pressed={panelsHidden} onClick={() => setPanelsHidden(value => !value)}>{panelsHidden ? 'Mostrar painéis' : 'Recolher painéis'}</button>
          <button aria-label="Reduzir movimento" aria-pressed={reducedMotion} disabled={systemReducedMotion} title={systemReducedMotion ? 'Preferência de movimento reduzido do sistema' : 'Reduzir animações da interface e do mapa'} onClick={() => setMotionReduced(value => !value)}>Movimento {reducedMotion ? '−' : '+'}</button>
        </nav>
      </header>
      <section className="orbital-workspace">
        <div className="map-stage">
          <LazyRadarMap mode={mapMode} vehicles={visibleVehicles} cameraTarget={cameraTarget} onVehicleSelect={setSelectedTripId} viewMode={mapMode === '3d' ? '3d' : '2d'} reducedMotion={reducedMotion} />
          <div className="map-caption"><span className="eyebrow">BERLIN / CARTOGRAFIA REAL</span><b>{mapMode === '3d' ? '3D OPCIONAL · DETALHE POR ZOOM' : mapMode === 'lite' ? 'MAPLIBRE LITE / SEM MODELOS' : 'PAINÉIS / MAPA DESLIGADO'}</b><small>{visibleVehicles.length} estimativas nos filtros · não GPS</small></div>
        </div>
        <aside className="network-panel hardware-panel" aria-label="Rede de transporte" hidden={panelsHidden}>
          <p className="eyebrow">REDE / SNAPSHOT</p>
          <strong className="snapshot-total" data-testid="snapshot-count">{snapshot ? vehicles.length : '—'}</strong>
          <p>posições estimadas no snapshot</p>
          <label className="search-field">
            <span>Buscar linha ou viagem</span>
            <input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="S41, U8, 100 ou ID…" />
          </label>
          <div className="category-filters" aria-label="Filtrar categoria">
            {CATEGORIES.map(([id, label]) => <button key={id} data-category={id} aria-pressed={category === id} onClick={() => setCategory(id)}>{label}</button>)}
          </div>
          <p className="filter-summary">{visibleVehicles.length} viagens nos filtros</p>
          {visibleVehicles.length === 0 && <p className="empty-state">{!snapshot ? 'Aguardando o primeiro snapshot válido.' : vehicles.length === 0 ? 'Snapshot válido sem posições estimadas.' : 'Nenhuma viagem corresponde aos filtros.'}</p>}
          <RouteList vehicles={visibleVehicles} selectedTripId={selectedVehicle?.trip_id ?? null} onSelect={setSelectedTripId} />
        </aside>
        <aside className="inspector-panel hardware-panel" aria-label="Inspeção da viagem" hidden={panelsHidden}>
          <p className="eyebrow">INSPEÇÃO / TRIPUPDATE</p>
          <TripInspector vehicle={selectedVehicle} onLocate={locateVehicle} />
          <p className="model-notice">Lite usa pontos nativos do mapa, sem Deck ou GLBs. O 3D opcional carrega modelos apenas por escolha explícita. Sem mapa mantém os painéis e a conexão; Lite ainda usa GPU.</p>
        </aside>
        <div className="bottom-console">
          {snapshot && connectionStatus !== 'open' && <p className="transport-warning" role="status">{connectionStatus === 'reconnecting' ? 'Último snapshot preservado; reconectando automaticamente.' : 'Último snapshot preservado; a conexão está indisponível.'}</p>}
          {snapshot && dataStatus === 'stale' && <p className="transport-warning" role="status">Dados antigos: {DATA_STATUS_REASON_LABELS[dataStatusReason]}; as posições permanecem visíveis, mas não são dados ativos.</p>}
          {rejectedMessages > 0 && <p className="transport-warning" role="status">{rejectedMessages} mensagens rejeitadas; apenas snapshots válidos alteram o mapa.</p>}
          <SnapshotTelemetry snapshot={snapshot} dataStatus={dataStatus} dataStatusReason={dataStatusReason} />
        </div>
      </section>
      <footer className="orbital-footer"><span className="estimate-disclosure">Estimativa por TripUpdate · não é GPS</span><span>Cartografia 3D ≠ simulador de trânsito · conexão não garante atualidade do feed</span></footer>
    </main>
  )
}

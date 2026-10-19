import type { CSSProperties } from 'react'

import type { EstimatedVehiclePosition } from '../realtime/vehiclePositions'
import { getBerlinTransitLineColor } from './berlinTransitColors'
import { routeLabel } from './transportPresentation'

const TIMING_LABELS = {
  schedule_only: 'Horário estático',
  realtime_delay: 'Atraso realtime aplicado',
  absolute_realtime_time: 'Horário realtime da parada',
} as const

export function TripInspector({ vehicle, onLocate }: {
  vehicle: EstimatedVehiclePosition | null
  onLocate: (vehicle: EstimatedVehiclePosition) => void
}) {
  if (!vehicle) {
    return <div className="inspector-empty"><span aria-hidden="true" className="target-mark">⌖</span><h2>Explore a rede.</h2><p>Selecione uma linha ou um veículo no mapa.</p><small>Inspeção de estimativas publicadas pelo backend. Sem extrapolação no navegador.</small></div>
  }

  return (
    <div
      className="trip-inspector"
      data-category={vehicle.vehicle_category ?? 'unknown'}
      style={{
        '--mode-color': getBerlinTransitLineColor(
          vehicle.route_short_name,
          vehicle.vehicle_category,
        ),
      } as CSSProperties}
    >
      <div className="trip-hero">
        <div><p className="eyebrow">LINHA / {vehicle.vehicle_category?.replace('_', '-') ?? 'SEM CATEGORIA'}</p><h2>{routeLabel(vehicle)}</h2><span className="estimate-tag">POSIÇÃO ESTIMADA</span></div>
        <div className="heading-instrument" aria-label={`Direção estimada ${vehicle.bearing_degrees.toFixed(1)} graus`}><span>N</span><b aria-hidden="true" style={{ transform: `rotate(${vehicle.bearing_degrees}deg)` }}>↑</b><small>{vehicle.bearing_degrees.toFixed(1)}°</small></div>
      </div>
      <div className="coordinate-plate"><span>WGS84 / LAT · LON</span><strong>{vehicle.latitude.toFixed(5)} / {vehicle.longitude.toFixed(5)}</strong></div>
      <dl className="trip-metrics">
        <div><dt>Velocidade estimada</dt><dd>{(vehicle.speed_mps * 3.6).toFixed(1)} <small>km/h</small></dd></div>
        <div><dt>Desvio do horário</dt><dd>{vehicle.delay_seconds === null ? <small>Sem evidência realtime</small> : `${vehicle.delay_seconds > 0 ? '+' : ''}${vehicle.delay_seconds} s`}</dd></div>
      </dl>
      <div className="stop-sequence">
        <div><span className="stop-node" aria-hidden="true" /><small>PARADA ANTERIOR · ID GTFS</small><b>{vehicle.previous_stop_id || 'Não informado'}</b></div>
        <div><span className="stop-node" aria-hidden="true" /><small>PRÓXIMA PARADA · ID GTFS</small><b>{vehicle.next_stop_id || 'Não informado'}</b></div>
      </div>
      <dl className="provenance-details">
        <div><dt>Próxima chegada estimada · UTC</dt><dd><time dateTime={vehicle.estimated_next_arrival}>{vehicle.estimated_next_arrival.replace('T', ' ').replace('Z', '')}</time></dd></div>
        <div><dt>Evidência temporal</dt><dd>{TIMING_LABELS[vehicle.timing_source]}</dd></div>
        <div><dt>Viagem · ID</dt><dd data-testid="inspector-trip">{vehicle.trip_id}</dd></div>
      </dl>
      <button className="locate-button" onClick={() => onLocate(vehicle)}>Localizar no mapa <span aria-hidden="true">↗</span></button>
    </div>
  )
}

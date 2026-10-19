import type { SnapshotFreshnessReason, SnapshotFreshnessStatus } from '../realtime/connectionPolicy'
import type { VehiclePositionSnapshot } from '../realtime/vehiclePositions'

const DATA_STATUS_LABELS: Record<SnapshotFreshnessStatus, string> = {
  awaiting: 'Aguardando dados',
  fresh: 'Dados recentes',
  stale: 'Dados antigos',
}

const DATA_STATUS_REASON_LABELS: Record<SnapshotFreshnessReason, string> = {
  awaiting_snapshot: 'nenhum snapshot aceito',
  recent_snapshot: 'snapshot recebido recentemente',
  no_recent_snapshot: 'nenhum snapshot válido recebido no limite esperado',
  invalid_timestamp: 'proveniência temporal inválida',
  future_timestamp: 'proveniência temporal futura',
  old_snapshot: 'timestamps do snapshot antigos',
}

type SnapshotTelemetryProps = Readonly<{
  snapshot: VehiclePositionSnapshot | null
  dataStatus?: SnapshotFreshnessStatus
  dataStatusReason?: SnapshotFreshnessReason
}>

export function SnapshotTelemetry({
  snapshot,
  dataStatus = 'awaiting',
  dataStatusReason = 'awaiting_snapshot',
}: SnapshotTelemetryProps) {
  return (
    <section
      className="snapshot-telemetry hardware-panel"
      aria-label="Telemetria do snapshot"
      data-cycle-id={snapshot?.cycle_id ?? ''}
      data-status={dataStatus}
      data-status-reason={dataStatusReason}
    >
      <div className="telemetry-heading">
        <span className="eyebrow">VBB / PUBLICAÇÃO AUTORITATIVA</span>
        <span className="telemetry-state" data-testid="data-status">
          {DATA_STATUS_LABELS[dataStatus]}
        </span>
        <span className="contract-tag">JSON · v1</span>
      </div>
      <small className="telemetry-reason">{DATA_STATUS_REASON_LABELS[dataStatusReason]}</small>
      <div className="telemetry-counters">
        <div><span>TripUpdates recebidos</span><strong>{snapshot?.statistics.trip_updates_received ?? '—'}</strong></div>
        <div><span>Posições estimadas</span><strong>{snapshot?.statistics.positions_estimated ?? '—'}</strong></div>
        <div><span>Suprimidas no ciclo</span><strong>{snapshot?.statistics.positions_suppressed ?? '—'}</strong></div>
      </div>
      <details className="snapshot-provenance">
        <summary>Proveniência / timestamps UTC</summary>
        <dl><div><dt>Ciclo</dt><dd>{snapshot?.cycle_id ?? 'Nenhum snapshot aceito'}</dd></div><div><dt>Observado no backend</dt><dd><time>{snapshot?.observed_at ?? '—'}</time></dd></div><div><dt>Feed</dt><dd><time>{snapshot?.feed_timestamp ?? 'Não informado'}</time></dd></div></dl>
      </details>
    </section>
  )
}

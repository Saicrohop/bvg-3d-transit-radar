import { useMemo, type CSSProperties } from 'react'

import type { EstimatedVehiclePosition } from '../realtime/vehiclePositions'
import { getBerlinTransitLineColor } from './berlinTransitColors'

import { routeLabel } from './transportPresentation'

export function RouteList({ vehicles, selectedTripId, onSelect }: {
  vehicles: readonly EstimatedVehiclePosition[]
  selectedTripId: string | null
  onSelect: (tripId: string) => void
}) {
  const routes = useMemo(() => {
    const groups = new Map<string, { first: EstimatedVehiclePosition; count: number; selected: boolean }>()
    for (const vehicle of vehicles) {
      const key = JSON.stringify([vehicle.vehicle_category, vehicle.route_id])
      const group = groups.get(key) ?? { first: vehicle, count: 0, selected: false }
      group.count += 1
      group.selected ||= vehicle.trip_id === selectedTripId
      groups.set(key, group)
    }
    return [...groups.entries()].sort(([, a], [, b]) => routeLabel(a.first).localeCompare(routeLabel(b.first), 'de', { numeric: true }))
  }, [vehicles, selectedTripId])

  return (
    <ul className="route-list" aria-label="Linhas no snapshot">
      {routes.map(([key, { first, count, selected }]) => (
        <li key={key}>
          <button
            className="route-row"
            data-category={first.vehicle_category ?? 'unknown'}
            style={{
              '--mode-color': getBerlinTransitLineColor(
                first.route_short_name,
                first.vehicle_category,
              ),
            } as CSSProperties}
            aria-pressed={selected}
            aria-label={`Inspecionar ${routeLabel(first)}`}
            onClick={() => onSelect(first.trip_id)}
          >
            <span className="route-badge">{routeLabel(first)}</span>
            <span className="route-meta"><b>{first.vehicle_category?.replace('_', '-') ?? 'Sem categoria'}</b><small>{count} {count === 1 ? 'viagem estimada' : 'viagens estimadas'}</small></span>
            <span className="route-arrow" aria-hidden="true">↗</span>
          </button>
        </li>
      ))}
    </ul>
  )
}

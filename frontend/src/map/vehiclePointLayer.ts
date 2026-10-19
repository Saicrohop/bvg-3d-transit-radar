import { ScatterplotLayer } from '@deck.gl/layers'

import type { EstimatedVehiclePosition } from '../realtime/vehiclePositions'
import { getBerlinTransitLineColorRgb } from '../ui/berlinTransitColors'

export const VEHICLE_FILL_COLOR = [231, 255, 73] as const
const VEHICLE_POSITION_TRANSITION = { getPosition: 1000 } as const

export function getVehiclePosition(
  vehicle: EstimatedVehiclePosition,
): [number, number] {
  return [vehicle.longitude, vehicle.latitude]
}

export function createVehiclePointLayer(
  vehicles: readonly EstimatedVehiclePosition[],
) {
  return new ScatterplotLayer<EstimatedVehiclePosition>({
    id: 'estimated-vehicle-points',
    data: vehicles,
    getPosition: getVehiclePosition,
    transitions: VEHICLE_POSITION_TRANSITION,
    getFillColor: (vehicle) =>
      getBerlinTransitLineColorRgb(
        vehicle.route_short_name,
        vehicle.vehicle_category,
      ),
    getLineColor: () => [238, 80, 63],
    getRadius: () => 18,
    radiusUnits: 'meters',
    radiusMinPixels: 5,
    radiusMaxPixels: 16,
    filled: true,
    stroked: true,
    lineWidthMinPixels: 1.5,
    pickable: true,
    opacity: 0.92,
  })
}

import { ScatterplotLayer } from '@deck.gl/layers'

import type { EstimatedVehiclePosition } from '../realtime/vehiclePositions'

export const VEHICLE_FILL_COLOR = [255, 210, 0] as const

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
    getFillColor: () => VEHICLE_FILL_COLOR,
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

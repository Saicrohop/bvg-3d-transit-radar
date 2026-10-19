import type { EstimatedVehiclePosition } from '../realtime/vehiclePositions'

export function routeLabel(vehicle: EstimatedVehiclePosition) {
  return vehicle.route_short_name || vehicle.route_id
}

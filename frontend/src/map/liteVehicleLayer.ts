import type { CircleLayerSpecification } from 'maplibre-gl'
import type { FeatureCollection, Point } from 'geojson'
import type { EstimatedVehiclePosition } from '../realtime/vehiclePositions'
import { getBerlinTransitLineColor } from '../ui/berlinTransitColors'

export const LITE_VEHICLE_SOURCE = 'estimated-vehicles-lite'
export const LITE_VEHICLE_LAYER: CircleLayerSpecification = {
  id: 'estimated-vehicles-lite-points',
  type: 'circle',
  source: LITE_VEHICLE_SOURCE,
  paint: {
    'circle-radius': ['interpolate', ['linear'], ['zoom'], 9, 3, 16, 6],
    'circle-color': ['get', 'route_color'],
    'circle-stroke-color': '#080917',
    'circle-stroke-width': 1,
    'circle-opacity': 0.95,
  },
}

type LiteVehicleProperties = {
  trip_id: string
  category: string
  route_short_name: string | null
  route_color: string
}

export function createLiteVehicleData(
  vehicles: readonly EstimatedVehiclePosition[],
): FeatureCollection<Point, LiteVehicleProperties> {
  return {
    type: 'FeatureCollection',
    features: vehicles.map(vehicle => ({
      type: 'Feature', id: vehicle.trip_id,
      geometry: { type: 'Point', coordinates: [vehicle.longitude, vehicle.latitude] },
      properties: {
        trip_id: vehicle.trip_id,
        category: vehicle.vehicle_category ?? 'unknown',
        route_short_name: vehicle.route_short_name,
        route_color: getBerlinTransitLineColor(
          vehicle.route_short_name,
          vehicle.vehicle_category,
        ),
      },
    })),
  }
}

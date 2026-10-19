import type { VehicleCategory } from '../realtime/vehiclePositions'

export const BERLIN_TRANSIT_LINE_COLORS: Readonly<Record<string, string>> = {
  S1: '#da6ba2',
  S15: '#da6ba2',
  S2: '#007734',
  S25: '#007734',
  S26: '#007734',
  S3: '#0066ad',
  S41: '#ad5937',
  S42: '#cb6418',
  S46: '#cd9c53',
  S47: '#cd9c53',
  S5: '#eb7405',
  S7: '#816da6',
  S75: '#816da6',
  S8: '#66aa22',
  S85: '#66aa22',
  S9: '#992746',
  U1: '#7dad4c',
  U2: '#da421e',
  U3: '#16683d',
  U4: '#f0d722',
  U5: '#7e5330',
  U6: '#8c6dab',
  U7: '#009bd5',
  U8: '#224f86',
  U9: '#f3791d',
}

const CATEGORY_FALLBACK_COLORS: Readonly<Record<VehicleCategory, string>> = {
  u_bahn: '#68b9ff',
  s_bahn: '#76ffc2',
  bus: '#ff92d8',
  tram: '#ff967c',
  regional: '#d0a4ff',
}

export const UNKNOWN_TRANSIT_COLOR = '#e7ff49'

export function getBerlinTransitLineColor(
  routeShortName: string | null,
  category: VehicleCategory | null,
): string {
  const line = routeShortName?.toUpperCase().replace(/\s+/g, '') ?? ''
  return (
    BERLIN_TRANSIT_LINE_COLORS[line] ??
    (category === null ? UNKNOWN_TRANSIT_COLOR : CATEGORY_FALLBACK_COLORS[category])
  )
}

export function getBerlinTransitLineColorRgb(
  routeShortName: string | null,
  category: VehicleCategory | null,
): [number, number, number] {
  const color = getBerlinTransitLineColor(routeShortName, category)
  return [
    Number.parseInt(color.slice(1, 3), 16),
    Number.parseInt(color.slice(3, 5), 16),
    Number.parseInt(color.slice(5, 7), 16),
  ]
}

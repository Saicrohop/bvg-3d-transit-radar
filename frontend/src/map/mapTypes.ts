import type { EstimatedVehiclePosition } from '../realtime/vehiclePositions'

export type MapDisplayMode = 'lite' | '3d' | 'off'
export type RadarMapProps = Readonly<{
  vehicles: readonly EstimatedVehiclePosition[]
  viewMode?: '3d' | '2d'
  cameraTarget?: Readonly<{ longitude: number; latitude: number; requestId: number }> | null
  reducedMotion?: boolean
  onVehicleSelect?: (tripId: string) => void
}>

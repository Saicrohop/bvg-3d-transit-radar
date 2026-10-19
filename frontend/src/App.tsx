import './App.css'

import { useEstimatedVehiclePositions } from './realtime/useEstimatedVehiclePositions'
import { OrbitalRadar } from './ui/OrbitalRadar'

const POSITIONS_WS_URL =
  import.meta.env.VITE_POSITIONS_WS_URL ?? 'ws://127.0.0.1:8000/ws/positions'

function RealtimeRadarView() {
  const state = useEstimatedVehiclePositions(POSITIONS_WS_URL)
  return <OrbitalRadar {...state} />
}

export default function App() {
  return <RealtimeRadarView />
}

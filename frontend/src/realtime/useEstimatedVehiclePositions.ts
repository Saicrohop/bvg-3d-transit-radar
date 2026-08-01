import { useEffect, useMemo, useState } from 'react'

import {
  isEstimatedVehiclePosition,
  normalizeEstimatedVehiclePosition,
  upsertVehiclePosition,
  type VehiclePositionsByTrip,
} from './vehiclePositions'

export type WebSocketConnectionStatus =
  | 'connecting'
  | 'open'
  | 'closed'
  | 'error'

export function useEstimatedVehiclePositions(url: string) {
  const [vehiclesByTrip, setVehiclesByTrip] = useState<VehiclePositionsByTrip>(
    {},
  )
  const [connectionStatus, setConnectionStatus] =
    useState<WebSocketConnectionStatus>('connecting')

  useEffect(() => {
    let isCurrentConnection = true
    const socket = new WebSocket(url)

    socket.onopen = () => {
      if (isCurrentConnection) {
        setConnectionStatus('open')
      }
    }
    socket.onmessage = (message) => {
      const event = parseEstimatedPosition(message.data)
      if (event !== null) {
        setVehiclesByTrip((current) => upsertVehiclePosition(current, event))
      }
    }
    socket.onerror = () => {
      if (isCurrentConnection) {
        setConnectionStatus('error')
      }
    }
    socket.onclose = () => {
      if (isCurrentConnection) {
        setConnectionStatus('closed')
      }
    }

    return () => {
      isCurrentConnection = false
      socket.close()
    }
  }, [url])

  const vehicles = useMemo(
    () => Object.values(vehiclesByTrip),
    [vehiclesByTrip],
  )

  return { connectionStatus, vehicles }
}

function parseEstimatedPosition(data: unknown) {
  if (typeof data !== 'string') {
    return null
  }

  try {
    const event: unknown = JSON.parse(data)
    return isEstimatedVehiclePosition(event)
      ? normalizeEstimatedVehiclePosition(event)
      : null
  } catch {
    return null
  }
}

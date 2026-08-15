import { useEffect, useMemo, useState } from 'react'

import {
  isEstimatedVehiclePosition,
  normalizeEstimatedVehiclePosition,
  upsertVehiclePosition,
  type EstimatedVehiclePosition,
  type VehiclePositionsByTrip,
} from './vehiclePositions'

export const POSITION_BATCH_QUIET_PERIOD_MS = 250

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
    let pendingFlush: ReturnType<typeof setTimeout> | null = null
    const pendingEventsByTrip = new Map<string, EstimatedVehiclePosition>()
    const socket = new WebSocket(url)

    const flushPendingEvents = () => {
      pendingFlush = null
      if (!isCurrentConnection || pendingEventsByTrip.size === 0) {
        return
      }

      const events = [...pendingEventsByTrip.values()]
      pendingEventsByTrip.clear()
      setVehiclesByTrip((current) =>
        events.reduce(upsertVehiclePosition, current),
      )
    }

    socket.onopen = () => {
      if (isCurrentConnection) {
        setConnectionStatus('open')
      }
    }
    socket.onmessage = (message) => {
      const event = parseEstimatedPosition(message.data)
      if (isCurrentConnection && event !== null) {
        pendingEventsByTrip.set(event.trip_id, event)
        if (pendingFlush !== null) {
          clearTimeout(pendingFlush)
        }
        pendingFlush = setTimeout(
          flushPendingEvents,
          POSITION_BATCH_QUIET_PERIOD_MS,
        )
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
      if (pendingFlush !== null) {
        clearTimeout(pendingFlush)
      }
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

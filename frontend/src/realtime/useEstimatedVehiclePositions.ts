import { useEffect, useState } from 'react'

import {
  calculateReconnectDelay,
  DEFAULT_CONNECTION_POLICY,
  evaluateSnapshotFreshness,
  type SnapshotFreshnessReason,
  type SnapshotFreshnessStatus,
} from './connectionPolicy'
import {
  parseVehiclePositionSnapshotMessage,
  type EstimatedVehiclePosition,
  type VehiclePositionSnapshot,
} from './vehiclePositions'

export type WebSocketConnectionStatus =
  | 'connecting'
  | 'open'
  | 'reconnecting'
  | 'closed'
  | 'error'

type ConnectionState = Readonly<{
  url: string
  connectionStatus: WebSocketConnectionStatus
  snapshot: VehiclePositionSnapshot | null
  lastSnapshotReceivedAtMs: number | null
  rejectedMessages: number
}>

const EMPTY_VEHICLES: readonly EstimatedVehiclePosition[] = []

function initialState(url: string): ConnectionState {
  return {
    url,
    connectionStatus: 'connecting',
    snapshot: null,
    lastSnapshotReceivedAtMs: null,
    rejectedMessages: 0,
  }
}

export function useEstimatedVehiclePositions(url: string) {
  const [state, setState] = useState(() => initialState(url))
  const [nowMs, setNowMs] = useState(() => Date.now())
  const currentState = state.url === url ? state : initialState(url)
  const freshness = evaluateSnapshotFreshness({
    snapshot: currentState.snapshot,
    receivedAtMs: currentState.lastSnapshotReceivedAtMs,
    nowMs,
  })

  useEffect(() => {
    let disposed = false
    let socket: WebSocket | null = null
    let reconnectTimer: number | null = null
    let reconnectAttempt = 0

    setState(current => current.url === url ? current : initialState(url))

    function isActive(candidate: WebSocket) {
      return !disposed && socket === candidate
    }

    function scheduleReconnect() {
      if (disposed || reconnectTimer !== null) {
        return
      }

      const delay = calculateReconnectDelay(reconnectAttempt, Math.random())
      reconnectAttempt += 1
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null
        connect(true)
      }, delay)
    }

    function connect(isRetry: boolean) {
      if (disposed) {
        return
      }

      setState(current => current.url === url
        ? { ...current, connectionStatus: isRetry ? 'reconnecting' : 'connecting' }
        : current)

      let candidate: WebSocket
      try {
        candidate = new WebSocket(url)
      } catch {
        setState(current => current.url === url
          ? { ...current, connectionStatus: 'error' }
          : current)
        return
      }
      socket = candidate

      candidate.onopen = () => {
        if (!isActive(candidate)) return
        setNowMs(Date.now())
        setState(current => current.url === url
          ? { ...current, connectionStatus: 'open' }
          : current)
      }

      candidate.onmessage = message => {
        if (!isActive(candidate)) return
        const nextSnapshot = parseVehiclePositionSnapshotMessage(message.data)
        if (nextSnapshot === null) {
          setState(current => current.url === url
            ? { ...current, rejectedMessages: current.rejectedMessages + 1 }
            : current)
          return
        }

        const receivedAtMs = Date.now()
        reconnectAttempt = 0
        setNowMs(receivedAtMs)
        setState(current => current.url === url
          ? {
              ...current,
              snapshot: nextSnapshot,
              lastSnapshotReceivedAtMs: receivedAtMs,
            }
          : current)
      }

      candidate.onerror = () => {
        if (!isActive(candidate)) return
        setState(current => current.url === url
          ? { ...current, connectionStatus: 'error' }
          : current)
        socket = null
        candidate.close()
        scheduleReconnect()
      }

      candidate.onclose = () => {
        if (!isActive(candidate)) return
        socket = null
        setNowMs(Date.now())
        setState(current => current.url === url
          ? { ...current, connectionStatus: 'reconnecting' }
          : current)
        scheduleReconnect()
      }
    }

    connect(false)

    return () => {
      disposed = true
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer)
        reconnectTimer = null
      }
      const activeSocket = socket
      socket = null
      activeSocket?.close()
    }
  }, [url])

  useEffect(() => {
    if (
      state.url !== url ||
      state.snapshot === null ||
      state.lastSnapshotReceivedAtMs === null
    ) {
      return undefined
    }

    const staleAt = getEarliestStaleTime(state.snapshot, state.lastSnapshotReceivedAtMs)
    const delay = Math.max(0, staleAt - Date.now())
    const timer = window.setTimeout(() => setNowMs(Date.now()), delay)
    return () => window.clearTimeout(timer)
  }, [state.lastSnapshotReceivedAtMs, state.snapshot, state.url, url])

  return {
    connectionStatus: currentState.connectionStatus,
    vehicles: currentState.snapshot?.positions ?? EMPTY_VEHICLES,
    snapshot: currentState.snapshot,
    rejectedMessages: currentState.rejectedMessages,
    dataStatus: freshness.status as SnapshotFreshnessStatus,
    dataStatusReason: freshness.reason as SnapshotFreshnessReason,
  }
}

function getEarliestStaleTime(
  snapshot: VehiclePositionSnapshot,
  receivedAtMs: number,
): number {
  const provenanceTimes = [
    Date.parse(snapshot.observed_at),
    snapshot.feed_timestamp === null ? Number.POSITIVE_INFINITY : Date.parse(snapshot.feed_timestamp),
    receivedAtMs,
  ]
  return Math.min(...provenanceTimes.map(timestamp => timestamp + DEFAULT_CONNECTION_POLICY.staleAfterMs))
}

import type { VehiclePositionSnapshot } from './vehiclePositions'

export type ConnectionPolicy = Readonly<{
  initialReconnectDelayMs: number
  maxReconnectDelayMs: number
  jitterRatio: number
  staleAfterMs: number
  maxFutureSkewMs: number
}>

export const DEFAULT_CONNECTION_POLICY = {
  initialReconnectDelayMs: 1_000,
  maxReconnectDelayMs: 30_000,
  jitterRatio: 0.2,
  staleAfterMs: 45_000,
  maxFutureSkewMs: 5_000,
} as const satisfies ConnectionPolicy

export type SnapshotFreshnessStatus = 'awaiting' | 'fresh' | 'stale'

export type SnapshotFreshnessReason =
  | 'awaiting_snapshot'
  | 'recent_snapshot'
  | 'no_recent_snapshot'
  | 'invalid_timestamp'
  | 'future_timestamp'
  | 'old_snapshot'

export type SnapshotFreshness = Readonly<{
  status: SnapshotFreshnessStatus
  reason: SnapshotFreshnessReason
}>

type SnapshotMetadata = Pick<
  VehiclePositionSnapshot,
  'feed_timestamp' | 'observed_at'
>

type SnapshotFreshnessInput = Readonly<{
  snapshot: SnapshotMetadata | null
  receivedAtMs: number | null
  nowMs: number
  policy?: ConnectionPolicy
}>

export function calculateReconnectDelay(
  attempt: number,
  randomValue: number,
  policy: ConnectionPolicy = DEFAULT_CONNECTION_POLICY,
): number {
  if (!Number.isSafeInteger(attempt) || attempt < 0) {
    throw new RangeError('Reconnect attempt must be a non-negative integer')
  }
  if (!Number.isFinite(randomValue) || randomValue < 0 || randomValue > 1) {
    throw new RangeError('Reconnect jitter must be between 0 and 1')
  }

  const exponentialDelay = policy.initialReconnectDelayMs * (2 ** attempt)
  const baseDelay = Math.min(policy.maxReconnectDelayMs, exponentialDelay)
  const jitter = (randomValue * 2 - 1) * policy.jitterRatio
  const jitteredDelay = baseDelay * (1 + jitter)

  return Math.min(policy.maxReconnectDelayMs, Math.max(0, jitteredDelay))
}

export function evaluateSnapshotFreshness({
  snapshot,
  receivedAtMs,
  nowMs,
  policy = DEFAULT_CONNECTION_POLICY,
}: SnapshotFreshnessInput): SnapshotFreshness {
  if (snapshot === null) {
    return { status: 'awaiting', reason: 'awaiting_snapshot' }
  }

  if (!Number.isFinite(nowMs) || receivedAtMs === null || !Number.isFinite(receivedAtMs)) {
    return { status: 'stale', reason: 'invalid_timestamp' }
  }

  const observedAtMs = parseUtcTimestamp(snapshot.observed_at)
  const feedTimestampMs = snapshot.feed_timestamp === null
    ? null
    : parseUtcTimestamp(snapshot.feed_timestamp)
  if (observedAtMs === null || (snapshot.feed_timestamp !== null && feedTimestampMs === null)) {
    return { status: 'stale', reason: 'invalid_timestamp' }
  }

  const snapshotTimestamps = feedTimestampMs === null
    ? [observedAtMs]
    : [observedAtMs, feedTimestampMs]
  const allTimestamps = [...snapshotTimestamps, receivedAtMs]
  if (allTimestamps.some(timestamp => timestamp > nowMs + policy.maxFutureSkewMs)) {
    return { status: 'stale', reason: 'future_timestamp' }
  }

  if (snapshotTimestamps.some(timestamp => nowMs - timestamp >= policy.staleAfterMs)) {
    return { status: 'stale', reason: 'old_snapshot' }
  }
  if (nowMs - receivedAtMs >= policy.staleAfterMs) {
    return { status: 'stale', reason: 'no_recent_snapshot' }
  }

  return { status: 'fresh', reason: 'recent_snapshot' }
}

const UTC_TIMESTAMP_PATTERN =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?Z$/

function parseUtcTimestamp(value: unknown): number | null {
  if (typeof value !== 'string') {
    return null
  }

  const match = UTC_TIMESTAMP_PATTERN.exec(value)
  const parsed = Date.parse(value)
  if (match === null || !Number.isFinite(parsed)) {
    return null
  }

  const timestamp = new Date(parsed)
  return timestamp.getUTCFullYear() === Number(match[1]) &&
    timestamp.getUTCMonth() + 1 === Number(match[2]) &&
    timestamp.getUTCDate() === Number(match[3]) &&
    timestamp.getUTCHours() === Number(match[4]) &&
    timestamp.getUTCMinutes() === Number(match[5]) &&
    timestamp.getUTCSeconds() === Number(match[6])
    ? parsed
    : null
}

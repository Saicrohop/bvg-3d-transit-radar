import { describe, expect, it } from 'vitest'

import type { VehiclePositionSnapshot } from './vehiclePositions'
import {
  calculateReconnectDelay,
  DEFAULT_CONNECTION_POLICY,
  evaluateSnapshotFreshness,
} from './connectionPolicy'

type SnapshotMetadata = Pick<VehiclePositionSnapshot, 'feed_timestamp' | 'observed_at'>

const NOW = Date.parse('2026-09-12T12:00:00Z')

function metadata(
  overrides: Partial<SnapshotMetadata> = {},
): SnapshotMetadata {
  return {
    feed_timestamp: '2026-09-12T11:59:59Z',
    observed_at: '2026-09-12T11:59:59Z',
    ...overrides,
  }
}

describe('connection policy', () => {
  it('exposes the approved conservative defaults', () => {
    expect(DEFAULT_CONNECTION_POLICY).toEqual({
      initialReconnectDelayMs: 1_000,
      maxReconnectDelayMs: 30_000,
      jitterRatio: 0.2,
      staleAfterMs: 45_000,
      maxFutureSkewMs: 5_000,
    })
  })

  it('calculates exponential reconnect delays with bounded deterministic jitter', () => {
    expect(calculateReconnectDelay(0, 0.5)).toBe(1_000)
    expect(calculateReconnectDelay(1, 0.5)).toBe(2_000)
    expect(calculateReconnectDelay(0, 0)).toBe(800)
    expect(calculateReconnectDelay(0, 1)).toBe(1_200)
    expect(calculateReconnectDelay(5, 0.5)).toBe(30_000)
    expect(calculateReconnectDelay(10, 1)).toBe(30_000)
  })

  it('rejects invalid reconnect inputs instead of producing an unsafe timer', () => {
    expect(() => calculateReconnectDelay(-1, 0.5)).toThrow(RangeError)
    expect(() => calculateReconnectDelay(1.5, 0.5)).toThrow(RangeError)
    expect(() => calculateReconnectDelay(0, -0.1)).toThrow(RangeError)
    expect(() => calculateReconnectDelay(0, 1.1)).toThrow(RangeError)
    expect(() => calculateReconnectDelay(0, Number.NaN)).toThrow(RangeError)
  })

  it('reports no snapshot as awaiting without depending on the clock', () => {
    expect(evaluateSnapshotFreshness({ snapshot: null, receivedAtMs: null, nowMs: NOW })).toEqual({
      status: 'awaiting',
      reason: 'awaiting_snapshot',
    })
  })

  it('reports a recent snapshot as fresh, including a valid empty snapshot', () => {
    expect(evaluateSnapshotFreshness({
      snapshot: metadata(),
      receivedAtMs: NOW - 1_000,
      nowMs: NOW,
    })).toEqual({ status: 'fresh', reason: 'recent_snapshot' })
  })

  it('marks a snapshot stale at the exact age boundary', () => {
    expect(evaluateSnapshotFreshness({
      snapshot: metadata({
        observed_at: '2026-09-12T11:59:15Z',
        feed_timestamp: '2026-09-12T11:59:15Z',
      }),
      receivedAtMs: NOW - 1_000,
      nowMs: NOW,
    })).toEqual({ status: 'stale', reason: 'old_snapshot' })
  })

  it('marks a fresh payload stale when its receipt has aged out', () => {
    expect(evaluateSnapshotFreshness({
      snapshot: metadata(),
      receivedAtMs: NOW - 45_000,
      nowMs: NOW,
    })).toEqual({ status: 'stale', reason: 'no_recent_snapshot' })
  })

  it('rejects invalid and future provenance timestamps as stale', () => {
    expect(evaluateSnapshotFreshness({
      snapshot: metadata({ observed_at: 'not-a-timestamp' }),
      receivedAtMs: NOW,
      nowMs: NOW,
    })).toEqual({ status: 'stale', reason: 'invalid_timestamp' })
    expect(evaluateSnapshotFreshness({
      snapshot: metadata({ observed_at: '2026-09-12T12:00:05.001Z' }),
      receivedAtMs: NOW,
      nowMs: NOW,
    })).toEqual({ status: 'stale', reason: 'future_timestamp' })
    expect(evaluateSnapshotFreshness({
      snapshot: metadata({ feed_timestamp: 'not-a-timestamp' }),
      receivedAtMs: NOW,
      nowMs: NOW,
    })).toEqual({ status: 'stale', reason: 'invalid_timestamp' })
  })

  it('checks both feed and observed timestamps for age and future skew', () => {
    expect(evaluateSnapshotFreshness({
      snapshot: metadata({ feed_timestamp: '2026-09-12T11:59:15Z' }),
      receivedAtMs: NOW,
      nowMs: NOW,
    })).toEqual({ status: 'stale', reason: 'old_snapshot' })
    expect(evaluateSnapshotFreshness({
      snapshot: metadata({ feed_timestamp: '2026-09-12T12:00:05.001Z' }),
      receivedAtMs: NOW,
      nowMs: NOW,
    })).toEqual({ status: 'stale', reason: 'future_timestamp' })
  })

  it('does not mutate the snapshot metadata or policy input', () => {
    const snapshot = Object.freeze(metadata())
    const policy = { ...DEFAULT_CONNECTION_POLICY }
    const before = JSON.stringify({ snapshot, policy })

    evaluateSnapshotFreshness({ snapshot, receivedAtMs: NOW, nowMs: NOW, policy })

    expect(JSON.stringify({ snapshot, policy })).toBe(before)
  })

  it('rejects non-finite clock values as invalid timestamp state', () => {
    expect(evaluateSnapshotFreshness({
      snapshot: metadata(),
      receivedAtMs: Number.NaN,
      nowMs: NOW,
    })).toEqual({ status: 'stale', reason: 'invalid_timestamp' })
  })
})

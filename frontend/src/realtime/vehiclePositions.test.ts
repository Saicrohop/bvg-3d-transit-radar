import { describe, expect, it } from 'vitest'

import { createEstimatedVehiclePosition } from '../test/estimatedVehiclePositionFixture'
import {
  isEstimatedVehiclePosition,
  parseVehiclePositionSnapshotMessage,
} from './vehiclePositions'

const firstPosition = createEstimatedVehiclePosition()

function snapshot(positions = [firstPosition]) {
  return {
    type: 'vehicle_position_snapshot',
    schema_version: 1,
    cycle_id: 'cycle-1',
    feed_timestamp: firstPosition.feed_timestamp,
    observed_at: firstPosition.observed_at,
    positions,
    statistics: {
      trip_updates_received: positions.length,
      positions_estimated: positions.length,
      positions_suppressed: 0,
    },
  }
}

describe('P8 snapshot message', () => {
  it('returns only documented P8 fields at every level', () => {
    const event = snapshot()
    const untrusted = {
      ...event, untrusted: 'envelope',
      statistics: { ...event.statistics, untrusted: 'statistics' },
      positions: [{ ...firstPosition, untrusted: 'position' }],
    }
    expect(parseVehiclePositionSnapshotMessage(JSON.stringify(untrusted))).toEqual(event)
  })

  it.each([undefined, null, {}, 'positions', 1])('rejects non-array positions %#', (positions) => {
    expect(parseVehiclePositionSnapshotMessage(JSON.stringify({
      ...snapshot(), positions,
    }))).toBeNull()
  })

  it.each(Object.keys(firstPosition))('rejects the whole snapshot if one row lacks %s', (field) => {
    const malformed: Record<string, unknown> = { ...firstPosition, trip_id: 'bad-trip' }
    delete malformed[field]
    const event = snapshot([firstPosition, createEstimatedVehiclePosition({ trip_id: 'bad-trip' })])
    expect(parseVehiclePositionSnapshotMessage(JSON.stringify({
      ...event, positions: [firstPosition, malformed],
    }))).toBeNull()
  })

  it('rejects duplicate trip IDs even if the records differ', () => {
    const event = snapshot([firstPosition, { ...firstPosition, longitude: 13.5 }])
    expect(parseVehiclePositionSnapshotMessage(JSON.stringify(event))).toBeNull()
  })

  it.each([
    ['feed_timestamp', null], ['feed_timestamp', '2026-07-19T10:38:21Z'],
    ['observed_at', '2026-07-19T10:40:00.123457Z'],
  ])('rejects nested provenance mismatch %s = %s', (field, value) => {
    const event = snapshot([{ ...firstPosition, [field]: value }])
    expect(parseVehiclePositionSnapshotMessage(JSON.stringify(event))).toBeNull()
  })

  it('rejects feed timestamps differing only by one microsecond', () => {
    const event = {
      ...snapshot([{ ...firstPosition, feed_timestamp: '2026-07-19T10:38:20.000001Z' }]),
      feed_timestamp: '2026-07-19T10:38:20.000002Z',
    }
    expect(parseVehiclePositionSnapshotMessage(JSON.stringify(event))).toBeNull()
  })

  it('accepts matching null feed timestamps', () => {
    const event = {
      ...snapshot([{ ...firstPosition, feed_timestamp: null }]), feed_timestamp: null,
    }
    expect(parseVehiclePositionSnapshotMessage(JSON.stringify(event))).toEqual(event)
  })

  it('rejects a null envelope feed timestamp when a row has one', () => {
    expect(parseVehiclePositionSnapshotMessage(JSON.stringify({
      ...snapshot(), feed_timestamp: null,
    }))).toBeNull()
  })

  it.each([undefined, null, [], true, 1, {}, {
    trip_updates_received: 1, positions_published: 1, positions_suppressed: 0,
  }])('rejects malformed or legacy statistics %#', (statistics) => {
    expect(parseVehiclePositionSnapshotMessage(JSON.stringify({
      ...snapshot(), statistics,
    }))).toBeNull()
  })

  it.each(['trip_updates_received', 'positions_estimated', 'positions_suppressed'])(
    'rejects invalid counter %s', (field) => {
      for (const value of [undefined, null, true, '1', -1, 0.5, Number.MAX_SAFE_INTEGER + 1]) {
        const event = snapshot()
        expect(parseVehiclePositionSnapshotMessage(JSON.stringify({
          ...event, statistics: { ...event.statistics, [field]: value },
        }))).toBeNull()
      }
    },
  )

  it.each([
    { trip_updates_received: 2, positions_estimated: 2, positions_suppressed: 0 },
    { trip_updates_received: 2, positions_estimated: 1, positions_suppressed: 0 },
    { trip_updates_received: Number.MAX_SAFE_INTEGER + 1,
      positions_estimated: 1, positions_suppressed: Number.MAX_SAFE_INTEGER },
  ])('rejects inconsistent statistics %#', (statistics) => {
    expect(parseVehiclePositionSnapshotMessage(JSON.stringify({
      ...snapshot(), statistics,
    }))).toBeNull()
  })

  it('accepts coherent suppressed counts in an empty snapshot', () => {
    const event = {
      ...snapshot([]),
      statistics: { trip_updates_received: 4, positions_estimated: 0, positions_suppressed: 4 },
    }
    expect(parseVehiclePositionSnapshotMessage(JSON.stringify(event))).toEqual(event)
  })

  it.each([
    ['type', undefined], ['type', 'other'],
    ['schema_version', undefined], ['schema_version', 0], ['schema_version', 2],
    ['schema_version', '1'], ['schema_version', true], ['schema_version', null],
    ['cycle_id', undefined], ['cycle_id', ''], ['cycle_id', '  \t'], ['cycle_id', 1],
    ['observed_at', undefined], ['observed_at', null],
    ['observed_at', '2026-02-30T10:40:00Z'],
    ['observed_at', '2026-07-19T24:00:00Z'],
    ['observed_at', '2026-07-19T10:40:00+00:00'],
    ['observed_at', '2026-07-19T10:40:00.1234567Z'],
    ['feed_timestamp', undefined], ['feed_timestamp', 'invalid'],
    ['feed_timestamp', '2026-07-19T10:40:00'],
  ])('rejects invalid envelope %s = %s', (field, value) => {
    const event = { ...snapshot(), [field]: value }
    expect(parseVehiclePositionSnapshotMessage(JSON.stringify(event))).toBeNull()
  })

  it.each(['', '.1', '.12', '.123', '.1234', '.12345', '.123456'])(
    'accepts UTC timestamps with fractional suffix %s', (fraction) => {
      const timestamp = `2024-02-29T10:40:00${fraction}Z`
      const position = createEstimatedVehiclePosition({
        observed_at: timestamp, feed_timestamp: timestamp,
        trip_update_timestamp: timestamp, estimated_next_arrival: timestamp,
        service_date: '2024-02-29',
      })
      const event = { ...snapshot([position]), observed_at: timestamp, feed_timestamp: timestamp }
      expect(parseVehiclePositionSnapshotMessage(JSON.stringify(event))).toEqual(event)
    },
  )

  it.each([
    '{', '', undefined, null, 1, true, {}, new ArrayBuffer(8),
    new Uint8Array([123]), new Blob(['{}']),
    JSON.stringify(firstPosition), '[]', 'true', '1', 'null',
  ])('rejects invalid transport or standalone input %#', (data) => {
    expect(parseVehiclePositionSnapshotMessage(data)).toBeNull()
  })

  it('accepts an authoritative empty snapshot', () => {
    const event = snapshot([])
    expect(parseVehiclePositionSnapshotMessage(JSON.stringify(event))).toEqual(event)
  })

  it('accepts a complete schema-v1 snapshot', () => {
    const event = snapshot()
    expect(parseVehiclePositionSnapshotMessage(JSON.stringify(event))).toEqual(event)
  })
})

describe('P8 estimated vehicle position', () => {
  it('accepts a complete nested position', () => {
    expect(isEstimatedVehiclePosition(firstPosition)).toBe(true)
  })

  it.each([
    'entity_id', 'shape_id', 'previous_stop_id', 'next_stop_id',
    'estimated_next_arrival', 'observed_at', 'vehicle_category', 'route_short_name',
    'position_status', 'feed_timestamp', 'trip_update_timestamp', 'service_date',
    'timing_source',
  ])('rejects a missing required %s', (field) => {
    const incomplete: Record<string, unknown> = { ...firstPosition }
    delete incomplete[field]
    expect(isEstimatedVehiclePosition(incomplete)).toBe(false)
  })

  it.each([
    ['schedule_only', 0], ['realtime_delay', null],
    ['absolute_realtime_time', null], ['realtime_delay', 1.5],
    ['realtime_delay', true], ['realtime_delay', '75'],
    ['unknown', 0],
  ])('rejects inconsistent timing %s / %s', (timing_source, delay_seconds) => {
    expect(isEstimatedVehiclePosition({
      ...firstPosition, timing_source, delay_seconds,
    })).toBe(false)
  })

  it.each([
    ['schedule_only', null], ['realtime_delay', 0],
    ['absolute_realtime_time', -75],
  ])('accepts consistent timing %s / %s', (timing_source, delay_seconds) => {
    expect(isEstimatedVehiclePosition({
      ...firstPosition, timing_source, delay_seconds,
    })).toBe(true)
  })

  it('accepts empty backend identifiers and labels where allowed', () => {
    expect(isEstimatedVehiclePosition({
      ...firstPosition, entity_id: '', shape_id: '', previous_stop_id: '',
      next_stop_id: '', route_short_name: '', vehicle_category: null,
    })).toBe(true)
  })

  it.each([
    ['longitude', -180.01], ['longitude', 180.01],
    ['latitude', -90.01], ['latitude', 90.01], ['speed_mps', -0.1],
    ['longitude', Infinity], ['latitude', NaN], ['bearing_degrees', Infinity],
    ['speed_mps', Infinity], ['entity_id', null], ['shape_id', 7],
    ['previous_stop_id', false], ['next_stop_id', []],
    ['trip_id', ''], ['route_id', ''],
  ])('rejects invalid position %s = %s', (field, value) => {
    expect(isEstimatedVehiclePosition({ ...firstPosition, [field]: value })).toBe(false)
  })

  it.each(['feed_timestamp', 'trip_update_timestamp', 'estimated_next_arrival', 'observed_at'])(
    'rejects a malformed %s', (field) => {
      expect(isEstimatedVehiclePosition({
        ...firstPosition, [field]: 'not-a-utc-timestamp',
      })).toBe(false)
    },
  )

  it('rejects an impossible UTC timestamp', () => {
    expect(isEstimatedVehiclePosition({
      ...firstPosition, feed_timestamp: '2026-02-30T10:38:20Z',
    })).toBe(false)
  })

  it('rejects an impossible service date', () => {
    expect(isEstimatedVehiclePosition({
      ...firstPosition, service_date: '2026-13-40',
    })).toBe(false)
  })

  it.each([
    ['type', 'feed_message'], ['source', 'gps'], ['is_estimated', false],
    ['position_status', 'observed'], ['vehicle_category', 'ferry'],
    ['route_short_name', 41],
  ])('rejects malformed %s', (field, value) => {
    expect(isEstimatedVehiclePosition({ ...firstPosition, [field]: value })).toBe(false)
  })
})

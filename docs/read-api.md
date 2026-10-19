# Read-only transit API (F2)

FastAPI exposes these endpoints on the existing local server at `http://127.0.0.1:8000`. All handlers are read-only, use bound SQL parameters, time out database work after 5 seconds, and return `Cache-Control: public, max-age=60` on successful responses. The server allows browser GETs from the local Vite origins on ports 5173 and 5175; no API credential is required while the server is bound to loopback.

## `GET /api/routes`

Lists static GTFS routes, sorted by short name and route ID. `active_vehicles` counts positions in the latest complete WebSocket snapshot; before the first snapshot it is zero.

```json
{
  "routes": [
    {
      "route_id": "17440_900",
      "route_short_name": "M10",
      "route_type": 900,
      "vehicle_category": "tram",
      "active_vehicles": 4
    }
  ]
}
```

`vehicle_category` follows the existing VBB classifier and is `null` for route types it does not recognize.

## `GET /api/routes/{route_id}/path`

`route_id` must match `[A-Za-z0-9._:-]{1,128}`. Unknown IDs return `404`; malformed IDs return `422`. The response contains at most the three shapes used by the most trips, encoded as GeoJSON `LineString`s. Stops and scheduled offsets come from the most-used stop pattern among those selected shapes. `bounds` is `[west, south, east, north]`, or `null` if no shape exists. Successful paths are kept in a bounded process-local cache for 60 seconds.

```json
{
  "route_id": "17440_900",
  "route_short_name": "M10",
  "vehicle_category": "tram",
  "shapes": [{"shape_id": "…", "trip_count": 61, "geojson": {"type": "LineString", "coordinates": [[13.4, 52.5], [13.5, 52.6]]}}],
  "stops": [{"stop_sequence": 0, "stop_id": "…", "stop_name": "…", "lon": 13.4, "lat": 52.5}],
  "scheduled_offsets": [{"stop_sequence": 0, "arrival_offset_s": 0}],
  "bounds": [13.4, 52.5, 13.5, 52.6]
}
```

## `GET /api/stops?bbox=west,south,east,north&limit=500&modes=tram,bus`

`bbox` is required and must contain finite WGS84 coordinates in west/south/east/north order, within longitude/latitude ranges, with no side wider than 5 degrees. The endpoint returns GTFS stops/platforms (`location_type=0`) and stations (`location_type=1`) intersecting the bbox. `limit` defaults to 500 and is constrained to 1–500. `modes` is optional comma-separated `u_bahn`, `s_bahn`, `bus`, `tram`, or `regional`; unsupported values return `422`. Parent stations inherit the known modes of their platforms.

```json
{
  "bbox": [13.3, 52.4, 13.5, 52.6],
  "stops": [{"stop_id": "…", "name": "…", "location_type": 0, "lat": 52.5, "lon": 13.4, "modes": ["tram"]}]
}
```

`gtfs.stop_vehicle_modes` is a backend-only materialized view indexed by stop and mode. The local GTFS post-import script refreshes it alongside route shapes; the migration populates it on the existing database. It is not exposed to PostgREST `anon`/`authenticated` roles.

## `GET /api/punctuality/daily?date=YYYY-MM-DD&limit=10&min_samples=40`

`date` defaults to the current date in `Europe/Berlin`. `limit` is 1–100 (default 10); `min_samples` is 1–1,000,000 (default 40). Ranking identity is `(route_id, vehicle_category)`, and the most/least lists may overlap if fewer than twice `limit` candidates qualify. `min_samples` filters the two ranking lists only. `totals.routes` counts distinct route IDs across all daily rollups; `totals.route_categories` counts all route/category rollups for the date. Sample, on-time, and late totals also cover all rollups, including those below `min_samples`. If that day has no rollup, the endpoint returns empty arrays and zero totals. A GET never refreshes or writes analytics tables.

```json
{
  "date": "2026-10-18",
  "most_punctual": [],
  "least_punctual": [],
  "totals": {"routes": 0, "route_categories": 0, "samples": 0, "on_time": 0, "late": 0}
}
```

Daily rollup creation/scheduling and Hermes memory updates are F5, not part of this read-API phase. Until that phase populates `analytics.route_daily_punctuality`, this endpoint correctly reports no ranking data.

## Verification

- Unit HTTP tests use an injected fake pool: `tests/test_api_routes.py` and `tests/test_api_cache.py`.
- Local Postgres integration tests cover real route geometry/stops, PostGIS stop-mode/station mapping, and daily ranking SQL; write fixtures are rolled back.
- The API does not change the WebSocket v1 snapshot contract. Browser/3D/GPU visual checks remain manual and are not performed by these tests.

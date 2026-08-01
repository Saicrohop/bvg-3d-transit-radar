# BVG 3D Transit Radar

## Current delivery gate

**Phase 1 — Supabase/PostGIS and static VBB GTFS**, **Phase 2 — server-side
TripUpdate interpolation**, **Phase 3 — local FastAPI/WebSocket delivery**, and
**Phase 4 — React/MapLibre/Deck.gl production visualization** are complete.

The production frontend consumes normalized estimated-position events and
groups recognized categories into calibrated `ScenegraphLayer`s:

- `s_bahn` → `/models/s_bahn_db.glb`;
- `u_bahn`, `bus`, and `tram` → `/models/bvg_bus.glb`;
- null/unknown categories and failed assets remain visible through the safe 2D
  estimated-point fallback.

The S-Bahn orientation is intentionally preserved as `[0, 180 - heading, 90]`.
The approved scales, translations, PBR lighting, and `LightingEffect` must not
be changed without a new calibration pass. Do not claim a `TripUpdate`
interpolation is a GPS-observed `VehiclePosition`.

The visual production screenshot is an operational validation step, not a code
fixture: it requires the upstream VBB feed to contain real `TripUpdate`s. Never
replace an empty feed with mocks when reporting live evidence.

## Architecture invariants

- Static GTFS lives in the private `gtfs` PostgreSQL schema.
- The browser must never download or parse VBB GTFS-Realtime Protobuf.
- Future GTFS-RT parsing belongs exclusively to a server-side Python service.
- The WebSocket may publish only normalized estimated-position events; it must
  never relay raw VBB GTFS-Realtime Protobuf to a client.
- The React client may consume only `ws://127.0.0.1:8000/ws/positions` (or an
  explicitly configured local equivalent), and must never fetch VBB GTFS-RT.
- The normal frontend map presents normalized positions as estimated points and
  uses approved scenegraphs for recognized categories. The separately labeled
  calibration mode may render local models with mock data; it must not represent
  mocked vehicles as live VBB service.
- Inspect Protobuf entity types before accessing vehicle-specific fields, and
  verify that the upstream feed is non-empty before claiming live evidence.
- Estimated positions must include `source=trip_update_interpolation` and
  `is_estimated=true`; suppress unsafe loop/branch estimates rather than
  fabricating a location.
- Use PostGIS WGS84 geometry (`EPSG:4326`) for map interchange and the
  appropriate local metric geometry for spatial calculations.
- Never commit credentials, `.env` files, service-role keys, database URLs, or
  downloaded operational data.

## Local development commands

```bash
npm run supabase:start
npm run supabase:reset
npm run supabase:status
npm run supabase:stop
npm run test:phase2:local
npm run codex -- login status
npm run antigravity -- --help
```

`supabase:reset` destroys the local development database and reapplies the
versioned migrations. It must not be used against a remote Supabase project.

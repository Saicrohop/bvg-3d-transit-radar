# Route punctuality analytics (Fase 1)

## Status

Fase 1 stores sampled punctuality aggregates only. The API, map layers, continuous browser motion, and scheduled daily close are later phases; no public WebSocket schema change is made here.

The analytics schema is private to the local Supabase/Postgres project. Its tables are not granted to `anon` or `authenticated`; the narrowly scoped functions can be invoked by `service_role`. The backend writes with its existing local Postgres pool.

## Metric definition

- One observation is one estimated vehicle position with a non-null `delay_seconds` in an accepted realtime snapshot.
- `delay_seconds <= 60` is on time; `delay_seconds > 60` is late. Early vehicles count as on time.
- A null delay (for example, schedule-only interpolation) is excluded from both numerator and denominator; it is not treated as zero.
- Counts are **vehicle observations**, not unique trips, service journeys, or an official BVG punctuality score. A line with more samples contributes more evidence; sample counts must accompany every ratio.
- Delay sums are signed. Mean delay can be negative when vehicles are early.

## Storage and aggregation

`analytics.route_observation_windows` stores one row per Berlin service date, UTC 15-minute bucket, GTFS route ID, and normalized vehicle category. The ingest function accepts one JSON aggregate per route/category per snapshot and adds its counts atomically. A cycle UUID deduplicates retries for 30 days. The ingest function rejects inconsistent counts and unsupported category values.

`analytics.route_daily_punctuality` is rebuilt idempotently from the windows for a requested date. `analytics.refresh_daily_line_ranking(date, min_samples=40, limit=10)` persists separate `most_punctual` and `least_punctual` orderings. The default 40-observation minimum avoids publishing a rank from a handful of sightings; callers can lower it for tests. Ranking identity is `(route_id, vehicle_category)`; top and bottom lists intentionally can overlap when fewer than `2 * limit` candidates qualify. Ties resolve deterministically by mean signed delay, route ID, then category.

The tables are not readable by PostgREST `anon`/`authenticated`; only `service_role` has table read privileges, and the restricted SQL functions are `SECURITY DEFINER` with a pinned search path. The current local worker still connects as the project’s `postgres` role, so database grants are defense in depth for API roles—not least-privilege isolation of that local process. A dedicated worker role is a separate hardening change.

These functions do not create a scheduler. A later phase will choose when to close a Berlin service day and how to store the daily report.

## Apply and test locally

```bash
supabase migration up --local
BVG_DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:55031/postgres' .venv/Scripts/python.exe -m pytest -m integration tests/integration/test_route_analytics_integration.py -q
.venv/Scripts/python.exe -m pytest tests/test_route_analytics.py tests/test_route_analytics_repository.py tests/test_worker_analytics.py -q
```

Never use `supabase db reset` to apply this migration. It is additive and runs without dropping GTFS data.

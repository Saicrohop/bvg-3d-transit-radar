from __future__ import annotations

from bvg_radar.api.cache import RoutePathCache


def test_route_path_cache_expires_entries_and_isolates_mutation() -> None:
    now = [0.0]
    cache = RoutePathCache(ttl_seconds=60, max_entries=2, clock=lambda: now[0])
    original = {"shapes": [{"shape_id": "shape-a"}]}
    cache.set("route-a", original)
    original["shapes"].append({"shape_id": "caller-added"})

    cached = cache.get("route-a")
    assert cached == {"shapes": [{"shape_id": "shape-a"}]}
    assert cached is not None
    cached["shapes"].append({"shape_id": "response-mutated"})
    assert cache.get("route-a") == {"shapes": [{"shape_id": "shape-a"}]}

    now[0] = 60.0
    assert cache.get("route-a") is None


def test_route_path_cache_evicts_least_recently_used_entry() -> None:
    now = [0.0]
    cache = RoutePathCache(ttl_seconds=60, max_entries=2, clock=lambda: now[0])
    cache.set("route-a", {"value": "a"})
    cache.set("route-b", {"value": "b"})
    assert cache.get("route-a") == {"value": "a"}
    cache.set("route-c", {"value": "c"})

    assert cache.get("route-a") == {"value": "a"}
    assert cache.get("route-b") is None
    assert cache.get("route-c") == {"value": "c"}

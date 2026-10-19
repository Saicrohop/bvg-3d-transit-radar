import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_realtime_cycle_benchmark import sample

from bvg_radar.realtime.benchmark import build_summary


@pytest.mark.parametrize("count,small", [(1, True), (5, True), (19, True), (20, False)])
def test_p95_summary_labels_small_sample_without_claiming_sustained_load(count, small):
    summary = build_summary(
        tuple(sample(1.0) for _ in range(count)),
        batch_size=256,
        target_cycle_seconds=15.0,
    )
    assert summary["p95_sample_count"] == count
    assert summary["p95_small_sample"] is small
    assert summary["percentile_method"] == "nearest_rank"
    assert summary["p95_is_sustained_load_evidence"] is False


def benchmark_script():
    path = (
        Path(__file__).resolve().parents[1] / "scripts" / "benchmark_realtime_cycle.py"
    )
    spec = importlib.util.spec_from_file_location("benchmark_realtime_cycle_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("field", ["iterations", "batch_size"])
@pytest.mark.parametrize("value", [True, 1.5, float("nan"), float("inf"), 0, -1])
def test_benchmark_script_rejects_invalid_counts_before_creating_pool(
    monkeypatch, field, value
):
    script = benchmark_script()
    monkeypatch.setenv(
        "BVG_DATABASE_URL", "postgresql://postgres:***@127.0.0.1:55031/postgres"
    )

    async def forbidden(**_kwargs):
        raise AssertionError("invalid benchmark configuration must not reach DB")

    monkeypatch.setattr(script.asyncpg, "create_pool", forbidden)
    args = SimpleNamespace(
        iterations=1,
        batch_size=256,
        target_cycle_seconds=15.0,
        feed_url="https://example.test/feed",
    )
    setattr(args, field, value)
    with pytest.raises(ValueError, match=field.replace("_", "-")):
        asyncio.run(script.run_benchmark(args))


def test_benchmark_script_labels_full_download_per_cycle(monkeypatch):
    script = benchmark_script()
    monkeypatch.setenv(
        "BVG_DATABASE_URL", "postgresql://postgres:***@127.0.0.1:55031/postgres"
    )
    pools = []

    class Pool:
        async def close(self):
            pools.append("closed")

    async def create_pool(**_kwargs):
        return Pool()

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    async def measure(**kwargs):
        return sample(1.0)

    monkeypatch.setattr(script.asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(script.aiohttp, "ClientSession", lambda **_kwargs: Session())
    monkeypatch.setattr(script, "measure_worker_cycle", measure)
    result = asyncio.run(
        script.run_benchmark(
            SimpleNamespace(
                iterations=2,
                batch_size=256,
                target_cycle_seconds=15.0,
                feed_url="https://example.test/feed",
            )
        )
    )
    assert result["scenario"] == "full_download_per_cycle"
    assert result["etag_policy"] == "new_source_each_iteration_no_conditional_requests"
    assert result["sampling"] == "sequential_cycles_not_sustained_load"
    assert pools == ["closed"]


@pytest.mark.parametrize("target", [float("nan"), float("inf"), float("-inf"), 0, -1])
def test_benchmark_script_rejects_invalid_target_before_creating_pool(
    monkeypatch, target
):
    script = benchmark_script()
    monkeypatch.setenv(
        "BVG_DATABASE_URL", "postgresql://postgres:***@127.0.0.1:55031/postgres"
    )

    async def forbidden(**_kwargs):
        raise AssertionError("invalid benchmark configuration must not reach DB")

    monkeypatch.setattr(script.asyncpg, "create_pool", forbidden)
    with pytest.raises(ValueError, match="target-cycle-seconds"):
        asyncio.run(
            script.run_benchmark(
                SimpleNamespace(
                    iterations=1,
                    batch_size=256,
                    target_cycle_seconds=target,
                    feed_url="https://example.test/feed",
                )
            )
        )

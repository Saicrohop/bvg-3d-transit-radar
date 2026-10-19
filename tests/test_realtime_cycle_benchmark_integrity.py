from dataclasses import fields, replace

import pytest
from test_realtime_cycle_benchmark import sample

from bvg_radar.realtime.benchmark import build_summary

COUNT_FIELDS = [
    "trip_updates_received",
    "matchable_trip_updates",
    "positions_published",
    "snapshots_published",
    "sql_queries",
    "payload_bytes",
]
DURATION_FIELDS = [
    field.name for field in fields(sample(1.0)) if field.name.endswith("seconds")
]


@pytest.mark.parametrize("field", COUNT_FIELDS)
@pytest.mark.parametrize("value", [-1, True, 1.5, float("nan"), float("inf")])
def test_benchmark_rejects_invalid_sample_counts(field, value):
    with pytest.raises(ValueError, match="sample"):
        build_summary(
            (replace(sample(1.0), **{field: value}),),
            batch_size=256,
            target_cycle_seconds=15.0,
        )


@pytest.mark.parametrize("field", DURATION_FIELDS)
@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
def test_benchmark_rejects_negative_or_nonfinite_durations(field, value):
    with pytest.raises(ValueError, match="sample"):
        build_summary(
            (replace(sample(1.0), **{field: value}),),
            batch_size=256,
            target_cycle_seconds=15.0,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"matchable_trip_updates": 11},
        {"positions_published": 9},
        {"snapshots_published": 0},
        {"snapshots_published": 2},
    ],
)
def test_benchmark_rejects_inconsistent_sample_evidence(changes):
    with pytest.raises(ValueError, match="sample"):
        build_summary(
            (replace(sample(1.0), **changes),),
            batch_size=256,
            target_cycle_seconds=15.0,
        )


@pytest.mark.parametrize("batch_size", [True, 1.5, float("nan"), float("inf"), 0, -1])
def test_benchmark_requires_positive_integer_batch_size(batch_size):
    with pytest.raises(ValueError, match="batch_size"):
        build_summary((sample(1.0),), batch_size=batch_size, target_cycle_seconds=15.0)

from dataclasses import replace

from test_realtime_cycle_benchmark import sample

from bvg_radar.realtime.benchmark import build_summary


def empty_cycle(snapshots=1):
    return replace(
        sample(1.0, sql_queries=0),
        trip_updates_received=0,
        matchable_trip_updates=0,
        positions_published=0,
        snapshots_published=snapshots,
    )


def test_benchmark_cannot_pass_data_gate_with_zero_positions_in_entire_sample():
    summary = build_summary(
        (replace(sample(1.0), positions_published=0),),
        batch_size=256,
        target_cycle_seconds=15.0,
    )
    assert summary["passed"] is False
    assert summary["performance_passed"] is True
    assert summary["data_gate_passed"] is False
    assert (
        summary["feed_data_passed"] is True
    )  # matchable identity is not a produced estimate


def test_benchmark_allows_legitimate_empty_cycles_in_representative_sample():
    summary = build_summary(
        (empty_cycle(), sample(1.0), empty_cycle(snapshots=0)),
        batch_size=256,
        target_cycle_seconds=15.0,
    )
    assert summary["passed"] is True
    assert summary["performance_passed"] is True
    assert summary["data_gate_passed"] is True


def test_benchmark_all_empty_sample_passes_performance_but_not_data_gate():
    summary = build_summary(
        (empty_cycle(), empty_cycle(snapshots=0)),
        batch_size=256,
        target_cycle_seconds=15.0,
    )
    assert summary["performance_passed"] is True
    assert summary["data_gate_passed"] is False
    assert summary["passed"] is False


def test_benchmark_data_evidence_does_not_hide_performance_failure():
    summary = build_summary((sample(16.0),), batch_size=256, target_cycle_seconds=15.0)
    assert summary["data_gate_passed"] is True
    assert summary["performance_passed"] is False
    assert summary["passed"] is False

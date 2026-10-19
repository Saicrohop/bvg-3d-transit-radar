"""Synthetic fixtures only: never open the user's Hermes state or cron file."""

import json
import sqlite3
from datetime import datetime, timezone

import pytest

from bvg_radar import hermes_metrics as metrics


@pytest.fixture(autouse=True)
def forbid_user_state(monkeypatch):
    def forbidden():
        raise AssertionError("Tests must not resolve user Hermes state")

    monkeypatch.setattr(metrics, "_state_db_path", forbidden)
    monkeypatch.setattr(metrics, "_cron_jobs_path", forbidden)


@pytest.fixture
def sessions(monkeypatch):
    # Each query closes its connection; a keeper retains this memory-only store.
    uri = "file:metrics-test?mode=memory&cache=shared"
    keeper = sqlite3.connect(uri, uri=True)
    keeper.execute("""
        CREATE TABLE sessions (
            id TEXT, model TEXT, billing_provider TEXT,
            started_at REAL, ended_at REAL, end_reason TEXT,
            input_tokens INTEGER, output_tokens INTEGER,
            estimated_cost_usd REAL, message_count INTEGER, source TEXT
        )
    """)
    keeper.execute("""
        CREATE TABLE session_model_usage (
            session_id TEXT, model TEXT, billing_provider TEXT,
            api_call_count INTEGER, input_tokens INTEGER, output_tokens INTEGER,
            estimated_cost_usd REAL, first_seen REAL
        )
    """)

    def connect():
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(metrics, "_connect", connect)
    try:
        yield keeper
    finally:
        keeper.close()


def freeze_utc_now(monkeypatch):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            # Local day differs from UTC; the metrics day must still be UTC.
            instant = datetime(2026, 10, 14, 23, 30, tzinfo=timezone.utc)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(metrics, "datetime", FrozenDatetime)
    return datetime(2026, 10, 14, tzinfo=timezone.utc).timestamp()


def test_today_uses_unix_utc_midnight_inclusively(monkeypatch, sessions):
    midnight = freeze_utc_now(monkeypatch)
    sessions.executemany(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("before", "old", "p", midnight - 0.001, midnight, "error", 900, 9, 9.0, 1, None),
            ("boundary", "m", "p", midnight, None, None, 7, 3, 0.5, 1, None),
            ("after", "n", "p", midnight + 1, midnight + 2, "error", 11, 5, 0.2, 1, None),
        ],
    )
    sessions.commit()

    stats = metrics.query_today_stats()

    assert stats["sessions_today"] == 2
    assert stats["input_tokens_today"] == 18
    assert stats["output_tokens_today"] == 8
    assert stats["total_tokens_today"] == 26
    assert stats["models_used"] == 2
    assert stats["cost_today_usd"] == pytest.approx(0.7)


@pytest.mark.parametrize("wrapped", [False, True])
def test_cron_inverts_valid_paused_fallback(monkeypatch, tmp_path, wrapped):
    jobs = [
        {"name": "paused", "schedule": "daily", "paused": True},
        {"name": "running", "schedule": "daily", "paused": False},
        {"name": "explicit", "schedule": "daily", "enabled": False, "paused": False},
    ]
    path = tmp_path / "synthetic-jobs.json"
    path.write_text(json.dumps({"jobs": jobs} if wrapped else jobs), encoding="utf-8")
    monkeypatch.setattr(metrics, "_cron_jobs_path", lambda: path)

    assert [(j.name, j.enabled) for j in metrics.query_cron_jobs()] == [
        ("paused", False), ("running", True), ("explicit", False)
    ]


@pytest.mark.parametrize("payload", [
    None, "jobs", 3, {"jobs": {}},
    [None, [], "job", {"name": [], "schedule": "daily", "enabled": True}],
    [{"name": "invalid", "schedule": "daily", "enabled": "false"}],
    [{"name": "invalid", "schedule": "daily", "enabled": 1}],
    [{"name": "invalid", "schedule": "daily", "paused": "false"}],
    [{"name": "invalid", "schedule": [], "paused": True}],
])
def test_cron_rejects_invalid_structure_or_flag_types(monkeypatch, tmp_path, payload):
    path = tmp_path / "synthetic-jobs.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(metrics, "_cron_jobs_path", lambda: path)
    assert metrics.query_cron_jobs() == []


def test_cron_does_not_invent_enabled_when_both_flags_are_missing(monkeypatch, tmp_path):
    path = tmp_path / "synthetic-jobs.json"
    path.write_text('[{"name":"unknown", "schedule":"daily"}]', encoding="utf-8")
    monkeypatch.setattr(metrics, "_cron_jobs_path", lambda: path)
    assert metrics.query_cron_jobs()[0].enabled is None


def test_open_and_closed_records_do_not_prove_success_or_live_agents(monkeypatch, sessions):
    midnight = freeze_utc_now(monkeypatch)
    sessions.executemany(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("open", "model", "provider", midnight, None, None, 1, 1, 0.0, 1, None),
            ("closed", "model", "provider", midnight + 1, midnight + 2, None, 1, 1, 0.0, 1, None),
            ("cancelled", "model", "provider", midnight + 2, midnight + 3, "cancelled", 1, 1, 0.0, 1, None),
            ("failed", "model", "provider", midnight + 3, midnight + 4, "error", 1, 1, 0.0, 1, None),
        ],
    )
    sessions.commit()
    stats = metrics.query_today_stats()
    assert stats["success_rate"] is None
    assert stats["sessions_active"] is None
    assert stats["sessions_open"] == 1
    assert stats["day_timezone"] == "UTC"
    assert stats["usage_attribution"] == "session_started_at"
    assert [entry.status for entry in metrics.query_recent_activity()] == [
        "failed", "ended", "ended", "open"
    ]
    assert metrics.query_recent_sessions()[-1].active is None

    monkeypatch.setattr(metrics, "query_model_usage", lambda: [
        metrics.ModelUsage("model", "provider", 99, 100, 200, 1.0, 4)
    ])
    monkeypatch.setattr(metrics, "query_token_breakdown", lambda: [])
    snapshot = metrics.build_snapshot()
    assert snapshot.active_agents is None
    assert snapshot.total_agents is None
    assert snapshot.success_rate is None


def test_empty_day_has_no_invented_success_rate(monkeypatch, sessions):
    freeze_utc_now(monkeypatch)
    assert metrics.query_today_stats()["success_rate"] is None


def test_session_usage_limit_selects_whole_sessions_before_model_breakdown(monkeypatch, sessions):
    sessions.executemany(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("multi", "model-a", "provider-a", 100.0, None, None, 60, 6, 0.6, 3, "cli"),
            ("second", "model-b", "provider-b", 200.0, None, None, 40, 4, 0.4, 1, "ui"),
            ("older", "model-c", "provider-c", 10.0, None, None, 5, 1, 0.1, 1, "cli"),
        ],
    )
    sessions.executemany(
        "INSERT INTO session_model_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("multi", "model-a", "provider-a", 1, 10, 1, 0.1, 100.0),
            ("multi", "model-b", "provider-b", 2, 20, 2, 0.2, 200.0),
            ("multi", "model-c", "provider-a", 3, 30, 3, 0.3, 300.0),
            ("second", "model-b", "provider-b", 1, 40, 4, 0.4, 250.0),
            ("older", "model-c", "provider-c", 1, 5, 1, 0.1, 10.0),
        ],
    )
    sessions.commit()

    result = metrics.query_session_usage(limit=2)

    assert [session.session_id for session in result] == ["multi", "second"]
    assert len(result[0].breakdown) == 3
    assert result[0].total_input == 60
    assert result[0].total_output == 6
    assert result[0].total_cost == pytest.approx(0.6)
    assert len(result[1].breakdown) == 1
    assert result[1].total_input == 40


def test_connection_is_read_only_and_does_not_create_missing_state(monkeypatch, tmp_path):
    path = tmp_path / "synthetic-state.db"
    monkeypatch.setattr(metrics, "_state_db_path", lambda: path)
    with pytest.raises(sqlite3.OperationalError):
        metrics._connect()
    assert not path.exists()

    seed = sqlite3.connect(path)
    seed.execute("CREATE TABLE synthetic (value INTEGER)")
    seed.commit()
    seed.close()
    conn = metrics._connect()
    try:
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
        assert conn.in_transaction
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("INSERT INTO synthetic VALUES (1)")
    finally:
        conn.close()

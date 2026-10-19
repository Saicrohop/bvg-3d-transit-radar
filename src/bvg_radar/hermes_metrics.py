"""Data-access layer for Hermes Agent state database.

Reads session history, token usage, model statistics, and cron job data
from the local Hermes installation on Windows.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _hermes_dir() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "hermes"


def _state_db_path() -> Path:
    return _hermes_dir() / "state.db"


def _cron_jobs_path() -> Path:
    return _hermes_dir() / "cron" / "jobs.json"


@dataclass(frozen=True, slots=True)
class ModelUsage:
    model: str
    provider: str
    api_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    session_count: int


@dataclass(frozen=True, slots=True)
class SessionSummary:
    session_id: str
    model: str
    provider: str
    started_at: str  # ISO 8601
    message_count: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    active: bool | None  # No live-agent heartbeat is available in session history.


@dataclass(frozen=True, slots=True)
class ActivityEntry:
    agent: str  # derived from model/provider
    task: str
    model: str
    status: str  # "ended" | "failed" | "open"; not task outcome or liveness.
    timestamp: str  # ISO 8601


@dataclass(frozen=True, slots=True)
class TokenBreakdown:
    model: str
    tokens: int
    percentage: float


@dataclass(frozen=True, slots=True)
class CronJob:
    name: str
    schedule: str
    enabled: bool | None


@dataclass(frozen=True, slots=True)
class DailyUsage:
    date: str  # YYYY-MM-DD (local time)
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass(frozen=True, slots=True)
class ProviderDailyUsage:
    date: str
    provider: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class SessionUsageRow:
    session_id: str
    model: str
    provider: str
    api_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    started_at: str  # ISO 8601
    message_count: int | None
    source: str | None


@dataclass
class SessionUsage:
    session_id: str
    started_at: str
    message_count: int | None
    source: str | None
    total_input: int
    total_output: int
    total_cost: float
    breakdown: list[SessionUsageRow] = field(default_factory=list)


@dataclass
class DashboardSnapshot:
    total_tasks_today: int = 0
    active_agents: int | None = None
    total_agents: int | None = None
    tokens_today: int = 0
    success_rate: float | None = None
    model_usage: list[ModelUsage] = field(default_factory=list)
    token_breakdown: list[TokenBreakdown] = field(default_factory=list)
    recent_activity: list[ActivityEntry] = field(default_factory=list)
    sessions: list[SessionSummary] = field(default_factory=list)
    cron_jobs: list[CronJob] = field(default_factory=list)


# ── DB helpers ──────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    """Open an existing store read-only; never create or migrate user state."""
    uri = _state_db_path().resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=1.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute("BEGIN")
    return conn


def _today_unix_utc() -> float:
    """Unix seconds at UTC midnight; sessions.started_at uses Unix seconds."""
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


# ── Queries ─────────────────────────────────────────────────────────────

def query_model_usage() -> list[ModelUsage]:
    conn = _connect()
    try:
        rows = conn.execute("""
            SELECT model, billing_provider,
                   SUM(api_call_count) as calls,
                   SUM(input_tokens) as inp,
                   SUM(output_tokens) as outp,
                   SUM(COALESCE(estimated_cost_usd, 0)) as cost,
                   COUNT(DISTINCT session_id) as sessions
            FROM session_model_usage
            GROUP BY model, billing_provider
            ORDER BY cost DESC
        """).fetchall()
        return [
            ModelUsage(
                model=r["model"],
                provider=r["billing_provider"] or "unknown",
                api_calls=r["calls"],
                input_tokens=r["inp"],
                output_tokens=r["outp"],
                cost_usd=r["cost"],
                session_count=r["sessions"],
            )
            for r in rows
        ]
    finally:
        conn.close()


def query_token_breakdown() -> list[TokenBreakdown]:
    conn = _connect()
    try:
        total = conn.execute(
            "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) FROM session_model_usage"
        ).fetchone()[0]
        if total == 0:
            return []
        rows = conn.execute("""
            SELECT model,
                   SUM(input_tokens + output_tokens) as tokens
            FROM session_model_usage
            GROUP BY model
            ORDER BY tokens DESC
        """).fetchall()
        return [
            TokenBreakdown(
                model=r["model"],
                tokens=r["tokens"],
                percentage=round(r["tokens"] / total * 100, 1),
            )
            for r in rows
        ]
    finally:
        conn.close()


def query_recent_sessions(limit: int = 12) -> list[SessionSummary]:
    conn = _connect()
    try:
        rows = conn.execute("""
            SELECT id, model, billing_provider, started_at, ended_at,
                   message_count, input_tokens, output_tokens,
                   COALESCE(estimated_cost_usd, 0) as cost
            FROM sessions
            ORDER BY started_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        results = []
        for r in rows:
            dt = datetime.fromtimestamp(r["started_at"], tz=timezone.utc)
            results.append(
                SessionSummary(
                    session_id=r["id"],
                    model=r["model"] or "unknown",
                    provider=r["billing_provider"] or "unknown",
                    started_at=dt.isoformat(),
                    message_count=r["message_count"] or 0,
                    input_tokens=r["input_tokens"] or 0,
                    output_tokens=r["output_tokens"] or 0,
                    cost_usd=r["cost"],
                    active=None,
                )
            )
        return results
    finally:
        conn.close()


def query_today_stats() -> dict[str, Any]:
    """Recorded totals attributed to sessions started today in UTC, not daily spend."""
    conn = _connect()
    try:
        today = _today_unix_utc()
        row = conn.execute("""
            SELECT COUNT(*) as sessions,
                   COALESCE(SUM(input_tokens), 0) as inp,
                   COALESCE(SUM(output_tokens), 0) as outp,
                   COALESCE(SUM(estimated_cost_usd), 0) as cost,
                   COUNT(DISTINCT model) as models
            FROM sessions
            WHERE started_at >= ?
        """, (today,)).fetchone()

        return {
            "day_timezone": "UTC",
            "usage_attribution": "session_started_at",
            "sessions_today": row["sessions"],
            "input_tokens_today": row["inp"],
            "output_tokens_today": row["outp"],
            "total_tokens_today": row["inp"] + row["outp"],
            "cost_today_usd": row["cost"],
            "models_used": row["models"],
            # Missing end_reason is not proof of success, nor is an open record
            # proof that its process still runs. Keep legacy keys as unknown.
            "success_rate": None,
            "sessions_active": None,
            "sessions_open": conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE started_at >= ? AND ended_at IS NULL",
                (today,),
            ).fetchone()[0],
        }
    finally:
        conn.close()


def query_recent_activity(limit: int = 10) -> list[ActivityEntry]:
    conn = _connect()
    try:
        rows = conn.execute("""
            SELECT s.id, s.model, s.billing_provider, s.started_at, s.ended_at, s.end_reason
            FROM sessions s
            ORDER BY s.started_at DESC
            LIMIT ?
        """, (limit,)).fetchall()

        entries = []
        for r in rows:
            dt = datetime.fromtimestamp(r["started_at"], tz=timezone.utc)
            agent = _agent_label(r["model"] or "unknown", r["billing_provider"] or "")

            if r["ended_at"] is None:
                status = "open"
            elif r["end_reason"] == "error":
                status = "failed"
            else:
                status = "ended"

            task = f"Session {r['id'][:16]}..."
            if r["model"]:
                task = f"Agent run with {r['model']}"

            entries.append(
                ActivityEntry(
                    agent=agent,
                    task=task,
                    model=r["model"] or "unknown",
                    status=status,
                    timestamp=dt.isoformat(),
                )
            )
        return entries
    finally:
        conn.close()


def query_cron_jobs() -> list[CronJob]:
    path = _cron_jobs_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("jobs")
        if not isinstance(data, list):
            return []
        jobs = []
        for item in data:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "Unnamed")
            schedule = item.get("schedule", "?")
            if not isinstance(name, str) or not isinstance(schedule, str):
                continue
            if any(key in item and not isinstance(item[key], bool)
                   for key in ("enabled", "paused")):
                continue
            enabled = item.get("enabled")
            if enabled is None and "paused" in item:
                enabled = not item["paused"]
            jobs.append(CronJob(name=name, schedule=schedule, enabled=enabled))
        return jobs
    except (json.JSONDecodeError, OSError):
        return []


# ── Token-usage queries (per session and per day) ───────────────────────

_PROVIDER_SQL = "COALESCE(NULLIF(billing_provider, ''), 'unknown')"


def _day_bucket(unix_ts: float) -> str:
    """Bucket a unix timestamp into a local YYYY-MM-DD day string."""
    return datetime.fromtimestamp(unix_ts).strftime("%Y-%m-%d")


def query_daily_usage(days: int = 14) -> list[DailyUsage]:
    """Aggregate token usage per local day across all model-usage rows."""
    conn = _connect()
    try:
        cutoff = datetime.now().timestamp() - days * 86400
        rows = conn.execute(
            f"""
            SELECT date(first_seen, 'unixepoch', 'localtime') as day,
                   SUM(input_tokens) as inp,
                   SUM(output_tokens) as outp,
                   SUM(COALESCE(estimated_cost_usd, 0)) as cost
            FROM session_model_usage
            WHERE first_seen >= ?
            GROUP BY day
            ORDER BY day
            """,
            (cutoff,),
        ).fetchall()

        by_day = {r["day"]: r for r in rows}
        # Fill gaps so the chart has a continuous axis.
        results = []
        today = datetime.now().date()
        for offset in range(days - 1, -1, -1):
            day = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
            r = by_day.get(day)
            results.append(
                DailyUsage(
                    date=day,
                    input_tokens=int(r["inp"]) if r else 0,
                    output_tokens=int(r["outp"]) if r else 0,
                    cost_usd=float(r["cost"]) if r else 0.0,
                )
            )
        return results
    finally:
        conn.close()


def query_daily_usage_by_provider(days: int = 14) -> list[ProviderDailyUsage]:
    """Aggregate token usage per local day and provider."""
    conn = _connect()
    try:
        cutoff = datetime.now().timestamp() - days * 86400
        rows = conn.execute(
            f"""
            SELECT date(first_seen, 'unixepoch', 'localtime') as day,
                   {_PROVIDER_SQL} as provider,
                   SUM(input_tokens) as inp,
                   SUM(output_tokens) as outp
            FROM session_model_usage
            WHERE first_seen >= ?
            GROUP BY day, provider
            ORDER BY day, provider
            """,
            (cutoff,),
        ).fetchall()
        return [
            ProviderDailyUsage(
                date=r["day"],
                provider=r["provider"],
                input_tokens=int(r["inp"]),
                output_tokens=int(r["outp"]),
            )
            for r in rows
        ]
    finally:
        conn.close()


def query_session_usage(limit: int = 25) -> list[SessionUsage]:
    """Group model-usage rows per session, with a per-model/provider breakdown.

    A long-running session may switch models mid-flight; each row of
    session_model_usage records one (session, model, provider) billing block,
    so grouping by that triple and rolling the blocks up per session yields an
    exact per-provider breakdown without double counting.
    """
    conn = _connect()
    try:
        rows = conn.execute(
            f"""
            WITH recent_sessions AS (
                SELECT session_id,
                       MIN(first_seen) as session_first_seen,
                       MAX(first_seen) as session_last_seen
                FROM session_model_usage
                GROUP BY session_id
                ORDER BY session_last_seen DESC, session_id
                LIMIT ?
            )
            SELECT u.session_id,
                   u.model,
                   {_PROVIDER_SQL.replace("billing_provider", "u.billing_provider")} as provider,
                   SUM(u.api_call_count) as calls,
                   SUM(u.input_tokens) as inp,
                   SUM(u.output_tokens) as outp,
                   SUM(COALESCE(u.estimated_cost_usd, 0)) as cost,
                   recent.session_first_seen as first_seen,
                   s.started_at,
                   s.message_count,
                   s.source
            FROM recent_sessions AS recent
            JOIN session_model_usage AS u
              ON u.session_id = recent.session_id
            LEFT JOIN sessions AS s ON s.id = u.session_id
            GROUP BY u.session_id,
                     u.model,
                     {_PROVIDER_SQL.replace("billing_provider", "u.billing_provider")},
                     recent.session_first_seen,
                     recent.session_last_seen,
                     s.started_at,
                     s.message_count,
                     s.source
            ORDER BY recent.session_last_seen DESC,
                     recent.session_first_seen DESC,
                     u.session_id,
                     u.model,
                     provider
            """,
            (limit,),
        ).fetchall()

        sessions: dict[str, SessionUsage] = {}
        for r in rows:
            sid = r["session_id"]
            started = r["started_at"] or r["first_seen"] or 0.0
            iso = datetime.fromtimestamp(started).isoformat(timespec="minutes")
            usage = sessions.get(sid)
            if usage is None:
                usage = SessionUsage(
                    session_id=sid,
                    started_at=iso,
                    message_count=r["message_count"],
                    source=r["source"],
                    total_input=0,
                    total_output=0,
                    total_cost=0.0,
                )
                sessions[sid] = usage
            row = SessionUsageRow(
                session_id=sid,
                model=r["model"],
                provider=r["provider"],
                api_calls=int(r["calls"]),
                input_tokens=int(r["inp"]),
                output_tokens=int(r["outp"]),
                cost_usd=float(r["cost"]),
                started_at=iso,
                message_count=r["message_count"],
                source=r["source"],
            )
            usage.breakdown.append(row)
            usage.total_input += row.input_tokens
            usage.total_output += row.output_tokens
            usage.total_cost += row.cost_usd

        ordered = [sessions[sid] for sid in dict.fromkeys(r["session_id"] for r in rows)]
        return ordered
    finally:
        conn.close()


# ── Helpers ─────────────────────────────────────────────────────────────

_MODEL_AGENT_MAP = {
    "deepseek": "deepseek-v4-pro",
    "gpt-5.6-terra": "openai-codex",
    "gpt-5.6-sol": "openai-codex",
    "gemini": "vertex",
}


def _agent_label(model: str, provider: str) -> str:
    """Map model/provider to a friendly agent name."""
    m = model.lower()
    if "deepseek" in m:
        return "Orchestrator"
    if "gemini" in m or "vertex" in provider.lower():
        return "Scout"
    if "codex" in provider.lower() or "gpt-5.6-terra" in m:
        return "Dev"
    if "gpt-5.6-sol" in m:
        return "Scribe"
    if "flash" in m:
        return "Reach"
    return model.split("/")[-1][:20]


def build_snapshot() -> DashboardSnapshot:
    """Assemble a complete dashboard data snapshot."""
    today = query_today_stats()
    models = query_model_usage()
    tokens = query_token_breakdown()
    activity = query_recent_activity()
    sessions = query_recent_sessions()

    return DashboardSnapshot(
        total_tasks_today=today["sessions_today"],
        tokens_today=today["total_tokens_today"],
        success_rate=today["success_rate"],
        model_usage=models,
        token_breakdown=tokens,
        recent_activity=activity,
        sessions=sessions,
    )

"""Data-access layer for Hermes Agent state database.

Reads session history, token usage, model statistics, and cron job data
from the local Hermes installation on Windows.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    active: bool


@dataclass(frozen=True, slots=True)
class ActivityEntry:
    agent: str  # derived from model/provider
    task: str
    model: str
    status: str  # "success" | "failed" | "active"
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
    enabled: bool


@dataclass
class DashboardSnapshot:
    total_tasks_today: int = 0
    active_agents: int = 0
    total_agents: int = 5
    tokens_today: int = 0
    success_rate: float = 0.0
    model_usage: list[ModelUsage] = field(default_factory=list)
    token_breakdown: list[TokenBreakdown] = field(default_factory=list)
    recent_activity: list[ActivityEntry] = field(default_factory=list)
    sessions: list[SessionSummary] = field(default_factory=list)
    cron_jobs: list[CronJob] = field(default_factory=list)


# ── DB helpers ──────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_state_db_path()))
    conn.row_factory = sqlite3.Row
    return conn


def _today_jd() -> float:
    """Julian day number for start of today (UTC)."""
    now = datetime.now(timezone.utc)
    # Julian day epoch is noon on 4713-11-24 BC
    # We approximate: unix epoch 1970-01-01 = JD 2440587.5
    unix_today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp()
    return unix_today / 86400.0 + 2440587.5


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
                    active=r["ended_at"] is None,
                )
            )
        return results
    finally:
        conn.close()


def query_today_stats() -> dict[str, Any]:
    conn = _connect()
    try:
        today = _today_jd()
        row = conn.execute("""
            SELECT COUNT(*) as sessions,
                   COALESCE(SUM(input_tokens), 0) as inp,
                   COALESCE(SUM(output_tokens), 0) as outp,
                   COALESCE(SUM(estimated_cost_usd), 0) as cost,
                   COUNT(DISTINCT model) as models
            FROM sessions
            WHERE started_at > ?
        """, (today,)).fetchone()

        success = conn.execute("""
            SELECT COUNT(*) FROM sessions
            WHERE started_at > ? AND end_reason IS NULL
        """, (today,)).fetchone()[0]
        failed = conn.execute("""
            SELECT COUNT(*) FROM sessions
            WHERE started_at > ? AND end_reason = 'error'
        """, (today,)).fetchone()[0]
        total_done = success + failed
        success_rate = (success / total_done * 100) if total_done > 0 else 100.0

        return {
            "sessions_today": row["sessions"],
            "input_tokens_today": row["inp"],
            "output_tokens_today": row["outp"],
            "total_tokens_today": row["inp"] + row["outp"],
            "cost_today_usd": row["cost"],
            "models_used": row["models"],
            "success_rate": round(success_rate, 1),
            "sessions_active": conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE started_at > ? AND ended_at IS NULL",
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
                status = "active"
            elif r["end_reason"] == "error":
                status = "failed"
            else:
                status = "success"

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
        if not isinstance(data, list):
            return []
        jobs = []
        for item in data:
            if isinstance(item, dict):
                jobs.append(
                    CronJob(
                        name=item.get("name", "Unnamed"),
                        schedule=item.get("schedule", "?"),
                        enabled=item.get("enabled", item.get("paused", True)),
                    )
                )
        return jobs
    except (json.JSONDecodeError, OSError):
        return []


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

    # Active model providers
    active_providers = {m.provider for m in models if m.api_calls > 0}
    active_agent_count = len(active_providers) if active_providers else 0

    return DashboardSnapshot(
        total_tasks_today=today["sessions_today"],
        active_agents=min(active_agent_count, 5),
        total_agents=5,
        tokens_today=today["total_tokens_today"],
        success_rate=today["success_rate"],
        model_usage=models,
        token_breakdown=tokens,
        recent_activity=activity,
        sessions=sessions,
    )

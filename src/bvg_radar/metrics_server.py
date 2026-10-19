"""Standalone FastAPI server exposing Hermes Agent metrics for the dashboard.

Run:  uv run uvicorn bvg_radar.metrics_server:app --host 127.0.0.1 --port 8001
"""

from __future__ import annotations

import os
from pathlib import Path

import psutil
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from .hermes_metrics import (
    build_snapshot,
    query_cron_jobs,
    query_daily_usage,
    query_daily_usage_by_provider,
    query_session_usage,
    query_today_stats,
)

def _resolve_dashboard_path() -> Path:
    """Locate mission-control-dashboard.html across known project layouts."""
    env_override = os.environ.get("HERMES_DASHBOARD_PATH")
    if env_override:
        return Path(env_override)
    candidates = [
        # Historic location inside the BVG repo (pre-reorg).
        Path(__file__).resolve().parent.parent.parent / "mission-control-dashboard.html",
        # Standalone dashboard project (current canonical location).
        Path(__file__).resolve().parent.parent.parent.parent
        / "mission-control-dashboard" / "mission-control-dashboard.html",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


_DASHBOARD_PATH = _resolve_dashboard_path()

app = FastAPI(title="Hermes Metrics API", version="1.0.0")

# Private telemetry is served only at these loopback authorities. CORS/Host
# checks are browser boundaries, not authentication; never bind this to a LAN.
_LOOPBACK_AUTHORITIES = ("127.0.0.1:8001", "localhost:8001", "[::1]:8001")
_ALLOWED_ORIGINS = tuple(f"http://{host}" for host in _LOOPBACK_AUTHORITIES)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET"],
    allow_headers=[],
    allow_credentials=False,
)


@app.middleware("http")
async def require_loopback_browser_context(request: Request, call_next):
    if request.headers.get("host") not in _LOOPBACK_AUTHORITIES:
        return JSONResponse({"detail": "Untrusted host"}, status_code=400)
    origin = request.headers.get("origin")
    if origin is not None and origin not in _ALLOWED_ORIGINS:
        return JSONResponse({"detail": "Untrusted origin"}, status_code=403)
    if request.headers.get("sec-fetch-site") == "cross-site":
        return JSONResponse({"detail": "Cross-site telemetry request denied"}, status_code=403)
    return await call_next(request)


@app.get("/")
def dashboard():
    """Serve the Mission Control Dashboard."""
    if _DASHBOARD_PATH.exists():
        return HTMLResponse(_DASHBOARD_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Dashboard not found</h1>", status_code=404)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "hermes-metrics"}


@app.get("/api/metrics")
def metrics():
    """Full dashboard snapshot."""
    snap = build_snapshot()

    return {
        "kpi": {
            "total_tasks_today": snap.total_tasks_today,
            "active_agents": snap.active_agents,
            "total_agents": snap.total_agents,
            "tokens_today": snap.tokens_today,
            "success_rate": snap.success_rate,
        },
        "model_usage": [
            {
                "model": m.model,
                "provider": m.provider,
                "api_calls": m.api_calls,
                "input_tokens": m.input_tokens,
                "output_tokens": m.output_tokens,
                "cost_usd": round(m.cost_usd, 4),
                "session_count": m.session_count,
            }
            for m in snap.model_usage
        ],
        "token_breakdown": [
            {"model": t.model, "tokens": t.tokens, "percentage": t.percentage}
            for t in snap.token_breakdown
        ],
        "recent_activity": [
            {
                "agent": a.agent,
                "task": a.task,
                "model": a.model,
                "status": a.status,
                "timestamp": a.timestamp,
            }
            for a in snap.recent_activity
        ],
        "sessions": [
            {
                "session_id": s.session_id,
                "model": s.model,
                "provider": s.provider,
                "started_at": s.started_at,
                "message_count": s.message_count,
                "input_tokens": s.input_tokens,
                "output_tokens": s.output_tokens,
                "cost_usd": round(s.cost_usd, 4),
                "active": s.active,
            }
            for s in snap.sessions
        ],
    }


@app.get("/api/system")
def system_metrics():
    """Live system hardware metrics."""
    cpu = psutil.cpu_percent(interval=0.2)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "cpu_percent": cpu,
        "ram_used_gb": round(mem.used / (1024**3), 1),
        "ram_total_gb": round(mem.total / (1024**3), 1),
        "ram_percent": mem.percent,
        "disk_used_gb": round(disk.used / (1024**3), 1),
        "disk_total_gb": round(disk.total / (1024**3), 1),
        "disk_percent": disk.percent,
        "cpu_cores": psutil.cpu_count(),
    }


@app.get("/api/activity")
def activity():
    """Recent agent activity log."""
    snap = build_snapshot()
    return {
        "activities": [
            {
                "agent": a.agent,
                "task": a.task,
                "model": a.model,
                "status": a.status,
                "timestamp": a.timestamp,
            }
            for a in snap.recent_activity
        ]
    }


@app.get("/api/cron")
def cron_jobs():
    """Scheduled cron jobs."""
    jobs = query_cron_jobs()
    return {
        "jobs": [
            {"name": j.name, "schedule": j.schedule, "enabled": j.enabled}
            for j in jobs
        ]
    }


@app.get("/api/stats/today")
def today_stats():
    """Today's aggregate statistics."""
    stats = query_today_stats()
    return stats


@app.get("/api/usage/daily")
def usage_daily(days: int = 14):
    """Token usage per day (input and output separated)."""
    if not 1 <= days <= 90:
        days = 14
    return {
        "days": [
            {
                "date": d.date,
                "input_tokens": d.input_tokens,
                "output_tokens": d.output_tokens,
                "total_tokens": d.input_tokens + d.output_tokens,
                "cost_usd": round(d.cost_usd, 4),
            }
            for d in query_daily_usage(days)
        ]
    }


@app.get("/api/usage/providers")
def usage_providers(days: int = 14):
    """Token usage per day per provider."""
    if not 1 <= days <= 90:
        days = 14
    return {
        "days": [
            {
                "date": p.date,
                "provider": p.provider,
                "input_tokens": p.input_tokens,
                "output_tokens": p.output_tokens,
                "total_tokens": p.input_tokens + p.output_tokens,
            }
            for p in query_daily_usage_by_provider(days)
        ]
    }


@app.get("/api/usage/sessions")
def usage_sessions(limit: int = 25):
    """Token usage per session, broken down by model/provider."""
    if not 1 <= limit <= 100:
        limit = 25
    sessions = query_session_usage(limit)
    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "started_at": s.started_at,
                "source": s.source,
                "message_count": s.message_count,
                "total_input_tokens": s.total_input,
                "total_output_tokens": s.total_output,
                "total_tokens": s.total_input + s.total_output,
                "total_cost_usd": round(s.total_cost, 4),
                "breakdown": [
                    {
                        "model": b.model,
                        "provider": b.provider,
                        "api_calls": b.api_calls,
                        "input_tokens": b.input_tokens,
                        "output_tokens": b.output_tokens,
                        "cost_usd": round(b.cost_usd, 4),
                    }
                    for b in s.breakdown
                ],
            }
            for s in sessions
        ]
    }

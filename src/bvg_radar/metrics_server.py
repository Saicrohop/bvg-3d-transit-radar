"""Standalone FastAPI server exposing Hermes Agent metrics for the dashboard.

Run:  uv run uvicorn bvg_radar.metrics_server:app --port 8001
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psutil
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from .hermes_metrics import build_snapshot, query_cron_jobs, query_today_stats

_DASHBOARD_PATH = Path(__file__).resolve().parent.parent.parent / "mission-control-dashboard.html"

app = FastAPI(title="Hermes Metrics API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def dashboard():
    """Serve the Mission Control Dashboard."""
    if _DASHBOARD_PATH.exists():
        return HTMLResponse(_DASHBOARD_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Dashboard not found</h1>", status_code=404)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "hermes-metrics"}


@app.get("/api/metrics")
async def metrics():
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
async def system_metrics():
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
async def activity():
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
async def cron_jobs():
    """Scheduled cron jobs."""
    jobs = query_cron_jobs()
    return {
        "jobs": [
            {"name": j.name, "schedule": j.schedule, "enabled": j.enabled}
            for j in jobs
        ]
    }


@app.get("/api/stats/today")
async def today_stats():
    """Today's aggregate statistics."""
    stats = query_today_stats()
    return stats

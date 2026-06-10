from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..database import get_db
from ..deps import get_current_user
from ..models import User, AgentMetricRecord
from ..services.metrics import metrics

router = APIRouter(tags=["metrics"])


@router.get("/api/metrics")
async def get_metrics(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    result = await db.execute(select(AgentMetricRecord).order_by(AgentMetricRecord.recorded_at))
    records = result.scalars().all()

    agents: dict = {}
    for r in records:
        s = agents.setdefault(r.agent, {"calls": 0, "errors": 0, "tool_calls": 0, "total_latency": 0.0, "samples": []})
        s["calls"] += 1
        s["errors"] += int(r.error)
        s["tool_calls"] += r.tool_calls
        s["total_latency"] += r.latency_ms
        s["samples"].append(r.latency_ms)

    out: dict = {}
    for name, s in agents.items():
        n = len(s["samples"])
        srt = sorted(s["samples"]) if n else []
        out[name] = {
            "calls": s["calls"],
            "errors": s["errors"],
            "error_rate": round(s["errors"] / s["calls"], 4) if s["calls"] else 0.0,
            "tool_calls": s["tool_calls"],
            "latency_avg_ms": round(s["total_latency"] / s["calls"], 1) if s["calls"] else 0.0,
            "latency_p50_ms": srt[n // 2] if srt else 0.0,
            "latency_p95_ms": srt[min(int(n * 0.95), n - 1)] if srt else 0.0,
            "latency_p99_ms": srt[min(int(n * 0.99), n - 1)] if srt else 0.0,
        }

    return {"uptime_seconds": metrics.snapshot()["uptime_seconds"], "agents": out}

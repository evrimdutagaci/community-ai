import asyncio
import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class _AgentStats:
    calls: int = 0
    errors: int = 0
    tool_calls: int = 0
    total_latency_ms: float = 0.0
    _samples: list = field(default_factory=list)


# Rolling window size for percentile calculations — unbounded history would grow forever
_MAX_SAMPLES = 1000


class MetricsStore:
    """
    Thread-safe in-memory metrics store.
    threading.Lock is needed because record_call can be called from a thread executor
    (e.g. the embedding model warm-up runs in a thread pool).
    Each call is also asynchronously persisted to the DB for historical analysis.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._agents: dict[str, _AgentStats] = defaultdict(_AgentStats)
        self._start_time = time.time()

    def record_call(
        self,
        agent: str,
        latency_ms: float,
        *,
        error: bool = False,
        tool_calls: int = 0,
    ) -> None:
        with self._lock:
            s = self._agents[agent]
            s.calls += 1
            s.errors += int(error)
            s.tool_calls += tool_calls
            s.total_latency_ms += latency_ms
            s._samples.append(round(latency_ms, 1))
            # Drop oldest samples once we exceed the rolling window
            if len(s._samples) > _MAX_SAMPLES:
                s._samples = s._samples[-_MAX_SAMPLES:]
        # Fire-and-forget DB write — metrics recording must never slow down the request path
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._persist(agent, latency_ms, error, tool_calls))
        except RuntimeError:
            pass

    async def _persist(self, agent: str, latency_ms: float, error: bool, tool_calls: int) -> None:
        try:
            from ..database import AsyncSessionLocal
            from ..models import AgentMetricRecord
            async with AsyncSessionLocal() as db:
                db.add(AgentMetricRecord(
                    agent=agent,
                    latency_ms=round(latency_ms, 1),
                    error=error,
                    tool_calls=tool_calls,
                ))
                await db.commit()
        except Exception:
            pass

    def snapshot(self) -> dict:
        """Return a point-in-time snapshot of all agent stats with percentile latencies."""
        with self._lock:
            agents: dict = {}
            for name, s in self._agents.items():
                n = len(s._samples)
                srt = sorted(s._samples) if n else []
                agents[name] = {
                    "calls": s.calls,
                    "errors": s.errors,
                    "error_rate": round(s.errors / s.calls, 4) if s.calls else 0.0,
                    "tool_calls": s.tool_calls,
                    "latency_avg_ms": round(s.total_latency_ms / s.calls, 1) if s.calls else 0.0,
                    "latency_p50_ms": srt[n // 2] if srt else 0.0,
                    "latency_p95_ms": srt[min(int(n * 0.95), n - 1)] if srt else 0.0,
                    "latency_p99_ms": srt[min(int(n * 0.99), n - 1)] if srt else 0.0,
                }
            return {
                "uptime_seconds": round(time.time() - self._start_time),
                "agents": agents,
            }


metrics = MetricsStore()

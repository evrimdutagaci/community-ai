import asyncio
import logging
from collections import deque
from datetime import datetime


class RecentLogsHandler(logging.Handler):
    """
    In-memory log handler that keeps the most recent N records and asynchronously
    persists each one to the database so the admin panel can display them.
    """

    def __init__(self, maxlen: int = 300):
        super().__init__()
        # appendleft keeps the newest record at index 0 so the admin panel shows most-recent-first
        self.records: deque = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord):
        try:
            log_record = {
                "time": datetime.utcfromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "exc": self.formatException(record.exc_info) if record.exc_info else None,
            }
            self.records.appendleft(log_record)
            # Fire-and-forget DB write — we don't want a log call to block the request path
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._persist(log_record))
            except RuntimeError:
                # No running event loop (e.g. during startup sync code) — skip DB persistence
                pass
        except Exception:
            self.handleError(record)

    async def _persist(self, record: dict) -> None:
        try:
            from ..database import AsyncSessionLocal
            from ..models import AppLog
            async with AsyncSessionLocal() as db:
                db.add(AppLog(
                    time=datetime.strptime(record["time"], "%Y-%m-%d %H:%M:%S"),
                    level=record["level"],
                    logger=record["logger"],
                    message=record["message"],
                    exc=record["exc"],
                ))
                await db.commit()
        except Exception:
            pass  # Never let a logging failure crash the application


recent_logs = RecentLogsHandler(maxlen=300)

import asyncio
import logging
from collections import deque
from datetime import datetime


class RecentLogsHandler(logging.Handler):
    def __init__(self, maxlen: int = 300):
        super().__init__()
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
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._persist(log_record))
            except RuntimeError:
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
            pass


recent_logs = RecentLogsHandler(maxlen=300)

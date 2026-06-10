from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from .config import settings

engine = create_async_engine(settings.database_url, echo=False)

# expire_on_commit=False prevents SQLAlchemy from expiring all attributes after a commit,
# which would trigger lazy-load errors in async contexts where the session is already closed.
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    """FastAPI dependency that yields a short-lived DB session per request."""
    async with AsyncSessionLocal() as session:
        yield session

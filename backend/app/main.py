import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from .database import engine, Base
from .routers import auth, communities, ws, dm, admin, metrics as metrics_router
from .services.logs import recent_logs

logging.getLogger().addHandler(recent_logs)
logging.getLogger().setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        # Each ALTER TABLE is wrapped in IF NOT EXISTS so these are safe to run on every startup.
        # This is intentional lightweight migration — avoids a full Alembic setup for a small schema.
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_digital BOOLEAN DEFAULT FALSE"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE"))
        await conn.execute(text("ALTER TABLE communities ADD COLUMN IF NOT EXISTS status_override VARCHAR(20)"))
        await conn.execute(text("ALTER TABLE communities ADD COLUMN IF NOT EXISTS location VARCHAR(100)"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE"))
        await conn.run_sync(Base.metadata.create_all)

    # Pre-warm the embedding model in a thread so the first user request isn't blocked by model load
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _warm_embeddings)

    # Backfill CommunityMembership rows for users that existed before the multi-community feature
    await _backfill_memberships()
    # Rename digital members to community-specific personas (handles deploys before unique naming was added)
    await _backfill_digital_member_names()

    # Background tasks — run concurrently throughout the application lifetime
    asyncio.create_task(_backfill_theme_embeddings())   # Communities created before theme_embedding feature
    asyncio.create_task(_backfill_digital_members())    # Communities missing digital members
    asyncio.create_task(_daily_announcements_loop())    # Refresh event announcements every midnight

    yield
    await engine.dispose()


async def _backfill_memberships():
    """
    Create CommunityMembership rows for legacy users.
    Users created before the multi-community feature only have community_id set —
    they need a corresponding membership row to appear in community member lists.
    """
    from sqlalchemy import select
    from .database import AsyncSessionLocal
    from .models import User, CommunityMembership

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.community_id.isnot(None), User.is_digital.is_(False))
        )
        for user in result.scalars().all():
            existing = await db.execute(
                select(CommunityMembership).where(
                    CommunityMembership.user_id == user.id,
                    CommunityMembership.community_id == user.community_id,
                )
            )
            if not existing.scalar_one_or_none():
                db.add(CommunityMembership(user_id=user.id, community_id=user.community_id))
        await db.commit()


def _warm_embeddings():
    from .services.embeddings import get_embedding_model
    get_embedding_model()


async def _backfill_digital_member_names():
    """
    Rename digital members to community-specific personas.
    Required for deployments that pre-date the unique-per-community naming scheme.

    Two-phase rename is necessary to break circular rename conflicts without hitting
    the unique constraint on username (e.g. aria.abc → aria.xyz when aria.xyz already exists).
    Phase 1 moves everyone to collision-safe temp names, then Phase 2 assigns final names.
    """
    from sqlalchemy import select
    from .database import AsyncSessionLocal
    from .models import Community, User
    from .services.digital_members import _personas_for_community, _username

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Community))
        for community in result.scalars().all():
            dm_result = await db.execute(
                select(User).where(
                    User.community_id == community.id,
                    User.is_digital.is_(True),
                ).order_by(User.created_at)
            )
            members = dm_result.scalars().all()
            if not members:
                continue
            personas = _personas_for_community(community.id)
            target_names = [_username(p["key"], community.id) for p in personas]

            # Skip if already correct — avoids unnecessary DB writes on a clean deploy
            if all(m.username == t for m, t in zip(members, target_names)):
                continue

            # Phase 1: move to collision-safe temp names to break any rename cycle
            for member in members:
                member.username = f"_tmp_{member.id}"
                member.email = f"_tmp_{member.id}@digital.community.ai"
            await db.flush()

            # Phase 2: assign final names
            for member, persona in zip(members, personas):
                new_uname = _username(persona["key"], community.id)
                member.username = new_uname
                member.email = f"{new_uname}@digital.community.ai"
            await db.flush()

        await db.commit()


async def _backfill_digital_members():
    """
    Ensure every community with fewer than 3 real members has digital members.
    Handles communities created before the digital member feature was added.
    """
    from sqlalchemy import select, func
    from .database import AsyncSessionLocal
    from .models import Community, User, CommunityMembership
    from .services.digital_members import ensure_digital_members

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Community))
        for community in result.scalars().all():
            real_result = await db.execute(
                select(func.count(CommunityMembership.user_id)).where(
                    CommunityMembership.community_id == community.id,
                )
            )
            real_count = real_result.scalar() or 0
            if real_count >= 3:
                continue  # Enough real members — digital members not needed
            digital_result = await db.execute(
                select(func.count(User.id)).where(
                    User.community_id == community.id,
                    User.is_digital.is_(True),
                )
            )
            if (digital_result.scalar() or 0) == 0:
                await ensure_digital_members(community, db)
        await db.commit()


async def _daily_announcements_loop():
    """
    Refresh event announcements for all communities once per day at midnight.
    Sleeps until the next midnight rather than using a fixed interval to avoid drift.
    """
    from sqlalchemy import select
    from .database import AsyncSessionLocal
    from .models import Community
    from .services.announcements import fetch_and_store_announcements

    logger = logging.getLogger(__name__)

    while True:
        now = datetime.now()
        midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        await asyncio.sleep((midnight - now).total_seconds())

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Community))
            for community in result.scalars().all():
                try:
                    await fetch_and_store_announcements(community, db, force=True)
                except Exception:
                    logger.exception("Announcement refresh failed for community %s", community.id)


async def _backfill_theme_embeddings():
    """
    Generate theme_embedding for communities created before this feature was added.
    Runs once at startup as a background task.
    """
    from sqlalchemy import select
    from .database import AsyncSessionLocal
    from .models import Community
    from .services.embeddings import embed_text

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Community))
        for community in result.scalars().all():
            if community.theme_embedding is None and community.name:
                theme_text = f"{community.name}. {community.description or ''}"
                community.theme_embedding = embed_text(theme_text)
        await db.commit()


app = FastAPI(title="Community AI", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(communities.router)
app.include_router(ws.router)
app.include_router(dm.router)
app.include_router(admin.router)
app.include_router(metrics_router.router)


@app.get("/health")
async def health():
    return {"status": "ok"}

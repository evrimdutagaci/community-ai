import asyncio
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from ..models import User, Community, CommunityMembership, CommunityMessage, CommunityBan
from .community_status import compute_status
from ..config import settings
from .embeddings import cosine_similarity, embed_text
from .agent import generate_community_name


def _community_score(user_embedding: list[float], community: Community) -> float:
    """
    Blend centroid similarity (who's in it) with theme similarity (what it's about).
    Falls back to centroid-only when theme_embedding is missing (legacy rows).
    """
    if community.centroid is None:
        return -1.0
    centroid_sim = cosine_similarity(user_embedding, list(community.centroid))
    if community.theme_embedding is None:
        return centroid_sim
    theme_sim = cosine_similarity(user_embedding, list(community.theme_embedding))
    return 0.5 * centroid_sim + 0.5 * theme_sim


RECOMMENDATION_THRESHOLD = 0.76  # Minimum blended similarity to suggest a community

async def get_recommendations(embedding: list[float], db: AsyncSession, n: int = 3, user: User | None = None) -> list[dict]:
    """Return top-N communities above the similarity threshold, sorted by score."""
    # Collect community IDs the user is banned from so we can exclude them
    banned_ids: set = set()
    if user is not None:
        ban_result = await db.execute(
            select(CommunityBan.community_id).where(CommunityBan.user_id == user.id)
        )
        banned_ids = {str(row) for row in ban_result.scalars().all()}

    result = await db.execute(select(Community))
    communities = result.scalars().all()

    scored = [
        (_community_score(embedding, c), c)
        for c in communities
        if c.centroid is not None and str(c.id) not in banned_ids
    ]
    scored.sort(key=lambda x: x[0], reverse=True)

    out = []
    for sim, c in scored[:n]:
        if sim < RECOMMENDATION_THRESHOLD:
            continue
        real_count = (await db.execute(
            select(func.count(CommunityMembership.user_id)).where(CommunityMembership.community_id == c.id)
        )).scalar() or 0
        last_msg = (await db.execute(
            select(func.max(CommunityMessage.created_at)).where(CommunityMessage.community_id == c.id)
        )).scalar()
        out.append({
            "id": str(c.id),
            "name": c.name,
            "description": c.description,
            "similarity": round(float(sim), 3),
            "status": compute_status(last_msg, real_count, c.status_override),
        })
    return out


async def assign_to_community(user: User, community_id: str | None, db: AsyncSession) -> Community:
    """Assign user to a specific community by id, or create a new one if community_id is None."""
    from uuid import UUID as _UUID
    embedding = list(user.embedding)

    if community_id:
        result = await db.execute(select(Community).where(Community.id == _UUID(community_id)))
        community = result.scalar_one_or_none()
        if not community:
            raise ValueError(f"Community {community_id} not found")
    else:
        community = await _create_community(user, embedding, db)

    user.community_id = community.id
    await _update_centroid(community, embedding, db)

    existing_m = await db.execute(
        select(CommunityMembership).where(
            CommunityMembership.user_id == user.id,
            CommunityMembership.community_id == community.id,
        )
    )
    if not existing_m.scalar_one_or_none():
        db.add(CommunityMembership(user_id=user.id, community_id=community.id))

    await db.commit()

    count_result = await db.execute(
        select(func.count(User.id)).where(User.onboarding_complete.is_(True))
    )
    total = count_result.scalar() or 0
    if total >= settings.recluster_every_n_users and total % settings.recluster_every_n_users == 0:
        asyncio.create_task(_recluster_background())

    return community


COMMUNITY_DEDUP_THRESHOLD = 0.88

async def _create_community(user: User, embedding: list[float], db: AsyncSession) -> Community:
    # If an existing community is already a very strong match, join it instead of creating a duplicate
    result = await db.execute(select(Community))
    for existing in result.scalars().all():
        if _community_score(embedding, existing) >= COMMUNITY_DEDUP_THRESHOLD:
            return existing

    name_data = await generate_community_name([user.profile_summary or ""])
    theme_text = f"{name_data['name']}. {name_data.get('description', '')}"
    community = Community(
        name=name_data["name"],
        description=name_data["description"],
        location=name_data.get("location") or None,
        centroid=embedding,
        theme_embedding=embed_text(theme_text),
    )
    db.add(community)
    await db.flush()
    from .digital_members import ensure_digital_members
    await ensure_digital_members(community, db)
    return community


async def _update_centroid(community: Community, new_embedding: list[float], db: AsyncSession):
    result = await db.execute(
        select(func.count(CommunityMembership.user_id)).where(
            CommunityMembership.community_id == community.id
        )
    )
    n = result.scalar() or 0

    if n == 0 or community.centroid is None:
        community.centroid = new_embedding
    else:
        old = np.array(community.centroid, dtype=float)
        new = np.array(new_embedding, dtype=float)
        community.centroid = ((old * n + new) / (n + 1)).tolist()


async def _recluster_background():
    from ..database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        await recluster_all(db)


async def recluster_all(db: AsyncSession):
    """Re-run k-means over all users and reassign communities."""
    from sklearn.cluster import KMeans

    result = await db.execute(select(User).where(User.embedding.isnot(None)))
    users = result.scalars().all()

    if len(users) < 4:
        return

    embeddings = np.array([list(u.embedding) for u in users], dtype=float)
    n_clusters = max(2, min(len(users) // 3, 10))

    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = kmeans.fit_predict(embeddings)

    cluster_users: dict[int, list[User]] = {}
    for user, label in zip(users, labels):
        cluster_users.setdefault(int(label), []).append(user)

    new_communities: dict[int, Community] = {}
    for cluster_id, members in cluster_users.items():
        profiles = [u.profile_summary for u in members if u.profile_summary]
        name_data = await generate_community_name(profiles)
        theme_text = f"{name_data['name']}. {name_data.get('description', '')}"
        community = Community(
            name=name_data["name"],
            description=name_data["description"],
            location=name_data.get("location") or None,
            centroid=kmeans.cluster_centers_[cluster_id].tolist(),
            theme_embedding=embed_text(theme_text),
        )
        db.add(community)
        await db.flush()
        new_communities[cluster_id] = community

    for user, label in zip(users, labels):
        user.community_id = new_communities[int(label)].id

    await db.commit()

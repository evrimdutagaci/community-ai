import json
import logging
import random
from uuid import UUID
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete as sql_delete, func
from jose import jwt, JWTError
from ..database import get_db

logger = logging.getLogger(__name__)
from ..models import User, OnboardingMessage, CommunityMessage, Community, CommunityWarning, CommunityMembership, CommunityBan
from ..services.agent import chat_onboarding, generate_profile
from ..services.embeddings import embed_text
from ..services.clustering import get_recommendations, assign_to_community
from ..services.moderation import moderate_message
from ..services.guardrails import rate_limiter, RATE_LIMITS, is_suspicious
from ..services.digital_members import (
    get_digital_members, get_real_member_count, remove_digital_members,
    generate_response_stream, display_name as digital_display_name,
)
from ..config import settings

router = APIRouter(tags=["websocket"])


def _msg_display(username: str, is_digital: bool) -> str:
    if is_digital:
        return username.split(".")[0].capitalize()
    return username


class ConnectionManager:
    def __init__(self):
        # room_id -> list of (websocket, username, user_id)
        self._rooms: dict[str, list[tuple[WebSocket, str, str]]] = {}

    async def connect(self, ws: WebSocket, room_id: str, username: str, user_id: str):
        await ws.accept()
        self._rooms.setdefault(room_id, []).append((ws, username, user_id))

    def register(self, ws: WebSocket, room_id: str, username: str, user_id: str):
        """Register a pre-accepted websocket."""
        self._rooms.setdefault(room_id, []).append((ws, username, user_id))

    def disconnect(self, ws: WebSocket, room_id: str):
        if room_id in self._rooms:
            self._rooms[room_id] = [
                (w, u, uid) for w, u, uid in self._rooms[room_id] if w is not ws
            ]

    async def broadcast(self, room_id: str, payload: dict):
        dead = []
        for ws, username, user_id in self._rooms.get(room_id, []):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append((ws, username, user_id))
        for item in dead:
            self._rooms[room_id].remove(item)

    async def kick_user(self, room_id: str, user_id: str):
        if room_id not in self._rooms:
            return
        to_kick = [(w, u, uid) for w, u, uid in self._rooms[room_id] if uid == user_id]
        self._rooms[room_id] = [(w, u, uid) for w, u, uid in self._rooms[room_id] if uid != user_id]
        for ws, _, _ in to_kick:
            try:
                await ws.send_json({"type": "kicked"})
                await ws.close(code=4003)
            except Exception:
                pass


manager = ConnectionManager()


async def _user_from_token(token: str, db: AsyncSession) -> User | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id: str | None = payload.get("sub")
        if not user_id:
            return None
        result = await db.execute(select(User).where(User.id == UUID(user_id)))
        return result.scalar_one_or_none()
    except (JWTError, ValueError):
        return None


# ── Onboarding WebSocket ──────────────────────────────────────────────────────

@router.websocket("/ws/onboarding")
async def onboarding_ws(
    websocket: WebSocket,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    user = await _user_from_token(token, db)
    await websocket.accept()
    if not user:
        await websocket.close(code=4001)
        return
    if user.is_banned:
        await websocket.send_json({"type": "banned", "content": "Your account has been banned. You cannot join communities or use the personal agent."})
        await websocket.close(code=4005)
        return
    if user.onboarding_complete:
        await websocket.close(code=4002)
        return

    # Load conversation history
    hist_result = await db.execute(
        select(OnboardingMessage)
        .where(OnboardingMessage.user_id == user.id)
        .order_by(OnboardingMessage.created_at)
    )
    history = [{"role": m.role, "content": m.content} for m in hist_result.scalars().all()]

    # On reconnect: restore history and re-send last recommendations if profile exists
    profile_ready = user.profile_summary is not None and user.embedding is not None

    # Build context so the agent can answer factual questions about the user
    mem_result = await db.execute(
        select(Community)
        .join(CommunityMembership, CommunityMembership.community_id == Community.id)
        .where(CommunityMembership.user_id == user.id)
    )
    current_communities = mem_result.scalars().all()

    if current_communities:
        names = ", ".join(f"'{c.name}'" for c in current_communities)
        user_context = (
            f"This user's username is {user.username}. "
            f"They are currently a member of {names} but are looking to join a new community."
        )
    else:
        user_context = (
            f"This user's username is {user.username}. "
            f"They are not currently a member of any community — they are here to find one."
        )

    if history:
        await websocket.send_json({"type": "history", "messages": history})
    elif not profile_ready:
        greeting = await chat_onboarding([], user_context)
        history.append({"role": "assistant", "content": greeting})
        db.add(OnboardingMessage(user_id=user.id, role="assistant", content=greeting))
        await db.commit()
        await websocket.send_json({"type": "message", "role": "assistant", "content": greeting})

    if profile_ready:
        recommendations = await get_recommendations(list(user.embedding), db, user=user)
        await websocket.send_json({"type": "recommendations", "communities": recommendations})

    # Single unified loop — handles chat messages AND community join selections
    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)

            # User chose a community
            if data.get("type") == "join" and profile_ready:
                community_id = data.get("community_id")
                # Check community-specific ban
                if community_id:
                    ban_check = await db.execute(
                        select(CommunityBan).where(
                            CommunityBan.user_id == user.id,
                            CommunityBan.community_id == UUID(community_id),
                        )
                    )
                    if ban_check.scalar_one_or_none():
                        await websocket.send_json({"type": "error", "content": "You have been banned from this community and cannot rejoin it."})
                        continue
                try:
                    community = await assign_to_community(user, community_id, db)
                except ValueError:
                    await websocket.send_json({"type": "error", "content": "Community not found, please try again."})
                    continue
                user.onboarding_complete = True
                await db.commit()
                await websocket.send_json({
                    "type": "onboarding_complete",
                    "community_id": str(community.id),
                    "community_name": community.name,
                })
                break

            # Regular chat message
            content = data.get("content", "").strip()
            if not content:
                continue

            limit, window = RATE_LIMITS["onboarding"]
            if not rate_limiter.is_allowed(f"{user.id}:onboarding", limit, window):
                await websocket.send_json({"type": "message", "role": "assistant", "content": "You're moving fast! Give me a moment to keep up."})
                continue

            if is_suspicious(content):
                await websocket.send_json({"type": "message", "role": "assistant", "content": "I can't help with that. Let's get back to finding your community."})
                continue

            history.append({"role": "user", "content": content})
            db.add(OnboardingMessage(user_id=user.id, role="user", content=content))
            await db.commit()

            user_turns = sum(1 for m in history if m["role"] == "user")

            ai_reply = await chat_onboarding(history, user_context)
            history.append({"role": "assistant", "content": ai_reply})
            db.add(OnboardingMessage(user_id=user.id, role="assistant", content=ai_reply))
            await db.commit()

            await websocket.send_json({"type": "message", "role": "assistant", "content": ai_reply})

            # Once enough turns, refresh profile + recommendations after every message
            if user_turns >= settings.min_messages_for_profile:
                profile = await generate_profile(history)
                user.profile_summary = profile
                user.embedding = embed_text(profile)
                await db.commit()
                profile_ready = True

                recommendations = await get_recommendations(list(user.embedding), db, user=user)
                await websocket.send_json({"type": "recommendations", "communities": recommendations})

    except WebSocketDisconnect:
        pass


# ── Community Chat WebSocket ──────────────────────────────────────────────────

@router.websocket("/ws/community/{community_id}")
async def community_ws(
    websocket: WebSocket,
    community_id: str,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    user = await _user_from_token(token, db)
    await websocket.accept()
    if not user:
        await websocket.close(code=4001)
        return
    membership_check = await db.execute(
        select(CommunityMembership).where(
            CommunityMembership.user_id == user.id,
            CommunityMembership.community_id == UUID(community_id),
        )
    )
    if not membership_check.scalar_one_or_none():
        await websocket.close(code=4003)
        return

    manager.register(websocket, community_id, user.username, str(user.id))

    # Fetch community object for digital member responses
    community_result = await db.execute(select(Community).where(Community.id == UUID(community_id)))
    community = community_result.scalar_one_or_none()

    # Send message history
    hist_result = await db.execute(
        select(CommunityMessage, User.username, User.is_digital)
        .join(User, CommunityMessage.user_id == User.id)
        .where(CommunityMessage.community_id == UUID(community_id))
        .order_by(CommunityMessage.created_at.desc())
        .limit(50)
    )
    history_rows = hist_result.all()
    recent = [
        {
            "type": "message",
            "id": str(msg.id),
            "user_id": str(msg.user_id),
            "username": username,
            "is_digital": is_digital,
            "content": msg.content,
            "created_at": msg.created_at.isoformat(),
        }
        for msg, username, is_digital in reversed(history_rows)
    ]
    await websocket.send_json({"type": "history", "messages": recent})

    await manager.broadcast(community_id, {
        "type": "system",
        "content": f"{user.username} joined the community",
    })

    # Digital member lifecycle checks on join
    real_count = await get_real_member_count(community_id, db)
    digital_members = await get_digital_members(community_id, db)

    if real_count >= 3 and digital_members:
        # Community has grown — retire digital members
        removed_names = await remove_digital_members(community_id, db)
        for name in removed_names:
            await manager.broadcast(community_id, {
                "type": "system",
                "content": f"{name} (AI member) has left — your community now has enough real members!",
            })
    elif digital_members and not history_rows and community:
        # Brand-new community — send welcome from 1–2 digital members
        try:
            welcomers = random.sample(digital_members, min(2, len(digital_members)))
            for dm in welcomers:
                await db.refresh(dm)
                await db.refresh(community)
                chunks: list[str] = []
                await manager.broadcast(community_id, {
                    "type": "stream_chunk", "user_id": str(dm.id),
                    "username": dm.username, "is_digital": True, "content": "",
                })
                async for chunk in generate_response_stream(community, dm, [], db=db, community_ids=[community_id]):
                    chunks.append(chunk)
                    await manager.broadcast(community_id, {
                        "type": "stream_chunk", "user_id": str(dm.id),
                        "username": dm.username, "is_digital": True, "content": chunk,
                    })
                dm_text = "".join(chunks)
                dm_msg = CommunityMessage(
                    user_id=dm.id,
                    community_id=UUID(community_id),
                    content=dm_text,
                )
                db.add(dm_msg)
                await db.commit()
                await db.refresh(dm_msg)
                await manager.broadcast(community_id, {
                    "type": "stream_end",
                    "id": str(dm_msg.id), "user_id": str(dm.id),
                    "username": dm.username, "is_digital": True,
                    "content": dm_text, "created_at": dm_msg.created_at.isoformat(),
                })
        except Exception:
            logger.exception("Digital welcome message failed")

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            content = data.get("content", "").strip()
            if not content:
                continue

            limit, window = RATE_LIMITS["community"]
            if not rate_limiter.is_allowed(f"{user.id}:community", limit, window):
                await websocket.send_json({"type": "system", "content": "⏱ You're sending messages too quickly. Please wait a moment."})
                continue

            if is_suspicious(content):
                warn_result = await db.execute(
                    select(CommunityWarning).where(
                        CommunityWarning.user_id == user.id,
                        CommunityWarning.community_id == UUID(community_id),
                    )
                )
                record = warn_result.scalar_one_or_none()
                if not record:
                    record = CommunityWarning(user_id=user.id, community_id=UUID(community_id), count=0)
                    db.add(record)
                record.count += 1
                await db.commit()
                await websocket.send_json({
                    "type": "warning",
                    "user_id": str(user.id),
                    "username": user.username,
                    "warning_number": record.count,
                    "content": f"⚠️ Moderator warning {record.count}/3 to {user.username}: message flagged for policy violation.",
                })
                if record.count >= 3:
                    try:
                        db.add(CommunityBan(user_id=user.id, community_id=UUID(community_id)))
                        await db.flush()
                    except Exception:
                        pass
                    ban_count = (await db.execute(
                        select(func.count(CommunityBan.id)).where(CommunityBan.user_id == user.id)
                    )).scalar() or 0
                    if ban_count >= 2:
                        user.is_banned = True
                    await db.execute(sql_delete(CommunityMembership).where(
                        CommunityMembership.user_id == user.id,
                        CommunityMembership.community_id == UUID(community_id),
                    ))
                    remaining = (await db.execute(
                        select(CommunityMembership).where(CommunityMembership.user_id == user.id)
                    )).scalars().all()
                    if remaining:
                        user.community_id = remaining[0].community_id
                    else:
                        user.community_id = None
                        user.onboarding_complete = False
                        await db.execute(sql_delete(OnboardingMessage).where(OnboardingMessage.user_id == user.id))
                    await db.commit()
                    await manager.broadcast(community_id, {
                        "type": "system",
                        "content": f"🚫 {user.username} has been removed by the moderator after 3 violations.",
                    })
                    await manager.kick_user(community_id, str(user.id))
                    return
                continue

            msg = CommunityMessage(
                user_id=user.id,
                community_id=UUID(community_id),
                content=content,
            )
            db.add(msg)
            await db.commit()
            await db.refresh(msg)

            await manager.broadcast(community_id, {
                "type": "message",
                "id": str(msg.id),
                "user_id": str(user.id),
                "username": user.username,
                "is_digital": False,
                "content": content,
                "created_at": msg.created_at.isoformat(),
            })

            # AI moderation
            is_violation, reason = await moderate_message(content)
            if is_violation:
                # Remove the offending message
                await db.execute(sql_delete(CommunityMessage).where(CommunityMessage.id == msg.id))
                await db.commit()
                await manager.broadcast(community_id, {"type": "delete", "id": str(msg.id)})
                warn_result = await db.execute(
                    select(CommunityWarning).where(
                        CommunityWarning.user_id == user.id,
                        CommunityWarning.community_id == UUID(community_id),
                    )
                )
                record = warn_result.scalar_one_or_none()
                if not record:
                    record = CommunityWarning(user_id=user.id, community_id=UUID(community_id), count=0)
                    db.add(record)
                record.count += 1
                await db.commit()

                if record.count >= 3:
                    # Permanently ban from this community
                    try:
                        db.add(CommunityBan(user_id=user.id, community_id=UUID(community_id)))
                        await db.flush()
                    except Exception:
                        pass  # upsert safety — already banned

                    # Count total community bans to decide global ban
                    ban_count = (await db.execute(
                        select(func.count(CommunityBan.id)).where(CommunityBan.user_id == user.id)
                    )).scalar() or 0
                    if ban_count >= 2:
                        user.is_banned = True

                    # Remove membership for this community
                    await db.execute(
                        sql_delete(CommunityMembership).where(
                            CommunityMembership.user_id == user.id,
                            CommunityMembership.community_id == UUID(community_id),
                        )
                    )
                    # Check remaining memberships
                    remaining = await db.execute(
                        select(CommunityMembership).where(CommunityMembership.user_id == user.id)
                    )
                    other = remaining.scalars().all()
                    if other:
                        user.community_id = other[0].community_id
                    else:
                        user.community_id = None
                        user.onboarding_complete = False
                        await db.execute(
                            sql_delete(OnboardingMessage).where(OnboardingMessage.user_id == user.id)
                        )
                    await db.commit()
                    await manager.broadcast(community_id, {
                        "type": "system",
                        "content": f"🚫 {user.username} has been removed by the moderator after 3 violations.",
                    })
                    await manager.kick_user(community_id, str(user.id))
                    return
                else:
                    await manager.broadcast(community_id, {
                        "type": "warning",
                        "user_id": str(user.id),
                        "username": user.username,
                        "warning_number": record.count,
                        "content": f"⚠️ Moderator warning {record.count}/3 to {user.username}: {reason}",
                    })

            # Digital member reply when community still needs them
            try:
                current_real_count = await get_real_member_count(community_id, db)
                if current_real_count < 3 and community:
                    current_digital = await get_digital_members(community_id, db)
                    if current_digital:
                        # Honour @Name mentions — find the tagged digital member
                        mentioned = next(
                            (
                                dm for dm in current_digital
                                if f"@{digital_display_name(dm)}".lower() in content.lower()
                            ),
                            None,
                        )
                        responder = mentioned if mentioned else random.choice(current_digital)
                        ctx_result = await db.execute(
                            select(CommunityMessage, User.username, User.is_digital)
                            .join(User, CommunityMessage.user_id == User.id)
                            .where(CommunityMessage.community_id == UUID(community_id))
                            .order_by(CommunityMessage.created_at.desc())
                            .limit(10)
                        )
                        ctx_msgs = [
                            {
                                "display_name": _msg_display(uname, is_dig),
                                "content": m.content,
                            }
                            for m, uname, is_dig in reversed(ctx_result.all())
                        ]
                        await db.refresh(community)
                        chunks: list[str] = []
                        await manager.broadcast(community_id, {
                            "type": "stream_chunk", "user_id": str(responder.id),
                            "username": responder.username, "is_digital": True, "content": "",
                        })
                        async for chunk in generate_response_stream(community, responder, ctx_msgs, db=db, community_ids=[community_id]):
                            chunks.append(chunk)
                            await manager.broadcast(community_id, {
                                "type": "stream_chunk", "user_id": str(responder.id),
                                "username": responder.username, "is_digital": True, "content": chunk,
                            })
                        dm_text = "".join(chunks)
                        dm_msg = CommunityMessage(
                            user_id=responder.id,
                            community_id=UUID(community_id),
                            content=dm_text,
                        )
                        db.add(dm_msg)
                        await db.commit()
                        await db.refresh(dm_msg)
                        await manager.broadcast(community_id, {
                            "type": "stream_end",
                            "id": str(dm_msg.id), "user_id": str(responder.id),
                            "username": responder.username, "is_digital": True,
                            "content": dm_text, "created_at": dm_msg.created_at.isoformat(),
                        })
            except Exception:
                logger.exception("Digital member reply failed")

    except WebSocketDisconnect:
        manager.disconnect(websocket, community_id)
        still_member = await db.execute(
            select(CommunityMembership).where(
                CommunityMembership.user_id == user.id,
                CommunityMembership.community_id == UUID(community_id),
            )
        )
        if still_member.scalar_one_or_none():
            await manager.broadcast(community_id, {
                "type": "system",
                "content": f"{user.username} left the community",
            })

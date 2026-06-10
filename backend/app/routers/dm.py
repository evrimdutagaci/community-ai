import json
import logging
from uuid import UUID
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_
from jose import jwt, JWTError
from ..database import get_db
from ..models import User, Community, DirectMessage, CommunityMembership
from ..deps import get_current_user
from ..config import settings
from ..services.digital_members import generate_dm_response_stream
from ..services.guardrails import rate_limiter, RATE_LIMITS, is_suspicious, validate_output

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dm"])


class DmManager:
    def __init__(self):
        self._rooms: dict[str, list[tuple[WebSocket, str, str]]] = {}

    async def connect(self, ws: WebSocket, room_id: str, username: str, user_id: str):
        await ws.accept()
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


dm_manager = DmManager()


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


@router.get("/api/dm/conversations")
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(DirectMessage)
        .where(
            or_(
                DirectMessage.sender_id == current_user.id,
                DirectMessage.receiver_id == current_user.id,
            )
        )
        .order_by(DirectMessage.created_at.desc())
    )
    messages = result.scalars().all()

    seen: set[UUID] = set()
    conversations = []
    for msg in messages:
        other_id = msg.receiver_id if msg.sender_id == current_user.id else msg.sender_id
        if other_id in seen:
            continue
        seen.add(other_id)
        user_result = await db.execute(select(User).where(User.id == other_id))
        other = user_result.scalar_one_or_none()
        if other:
            conversations.append({
                "user_id": str(other.id),
                "username": other.username,
                "last_message": msg.content,
                "last_message_at": msg.created_at.isoformat(),
            })
    return conversations


@router.websocket("/ws/dm/{other_user_id}")
async def dm_ws(
    websocket: WebSocket,
    other_user_id: str,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    user = await _user_from_token(token, db)
    await websocket.accept()
    if not user:
        await websocket.close(code=4001)
        return
    if user.is_banned:
        await websocket.send_json({"type": "banned", "content": "Your account has been banned. You cannot use the personal agent."})
        await websocket.close(code=4005)
        return

    other_result = await db.execute(select(User).where(User.id == UUID(other_user_id)))
    other_user = other_result.scalar_one_or_none()
    if not other_user:
        await websocket.close(code=4004)
        return

    # Canonical room ID so both sides join the same room
    room_id = "_".join(sorted([str(user.id), other_user_id]))
    await dm_manager.connect(websocket, room_id, user.username, str(user.id))

    # Load history (last 50 messages, oldest first)
    hist_result = await db.execute(
        select(DirectMessage)
        .where(
            or_(
                and_(
                    DirectMessage.sender_id == user.id,
                    DirectMessage.receiver_id == UUID(other_user_id),
                ),
                and_(
                    DirectMessage.sender_id == UUID(other_user_id),
                    DirectMessage.receiver_id == user.id,
                ),
            )
        )
        .order_by(DirectMessage.created_at.desc())
        .limit(50)
    )
    history = [
        {
            "type": "message",
            "id": str(m.id),
            "sender_id": str(m.sender_id),
            "sender_username": (user.username if m.sender_id == user.id else other_user.username),
            "content": m.content,
            "created_at": m.created_at.isoformat(),
        }
        for m in reversed(hist_result.scalars().all())
    ]
    await websocket.send_json({"type": "history", "messages": history})

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            content = data.get("content", "").strip()
            if not content:
                continue

            limit, window = RATE_LIMITS["dm"]
            if not rate_limiter.is_allowed(f"{user.id}:dm", limit, window):
                await websocket.send_json({"type": "system", "content": "⏱ You're sending messages too quickly."})
                continue

            if is_suspicious(content):
                await websocket.send_json({"type": "system", "content": "⚠️ Your message was flagged and not sent."})
                continue

            msg = DirectMessage(
                sender_id=user.id,
                receiver_id=UUID(other_user_id),
                content=content,
            )
            db.add(msg)
            await db.commit()
            await db.refresh(msg)

            await dm_manager.broadcast(room_id, {
                "type": "message",
                "id": str(msg.id),
                "sender_id": str(user.id),
                "sender_username": user.username,
                "content": content,
                "created_at": msg.created_at.isoformat(),
            })

            # Generate AI reply if the other participant is a digital member
            if other_user.is_digital:
                try:
                    # Resolve all the real user's communities for context
                    comm_result = await db.execute(
                        select(Community)
                        .join(CommunityMembership, CommunityMembership.community_id == Community.id)
                        .where(CommunityMembership.user_id == user.id)
                    )
                    user_communities = comm_result.scalars().all()
                    if user_communities:
                        community_name = ", ".join(c.name for c in user_communities)
                        community_description = user_communities[0].description if len(user_communities) == 1 else None
                        community_location = user_communities[0].location if len(user_communities) == 1 else None
                    else:
                        community_name = None
                        community_description = None
                        community_location = None

                    # Fetch recent DM history for context
                    ctx_result = await db.execute(
                        select(DirectMessage)
                        .where(
                            or_(
                                and_(
                                    DirectMessage.sender_id == user.id,
                                    DirectMessage.receiver_id == UUID(other_user_id),
                                ),
                                and_(
                                    DirectMessage.sender_id == UUID(other_user_id),
                                    DirectMessage.receiver_id == user.id,
                                ),
                            )
                        )
                        .order_by(DirectMessage.created_at.desc())
                        .limit(10)
                    )
                    ctx_msgs = [
                        {
                            "sender_username": (
                                user.username if m.sender_id == user.id else other_user.username
                            ),
                            "content": m.content,
                        }
                        for m in reversed(ctx_result.scalars().all())
                    ]

                    await db.refresh(other_user)
                    chunks: list[str] = []
                    await dm_manager.broadcast(room_id, {
                        "type": "stream_chunk",
                        "sender_id": str(other_user.id),
                        "sender_username": other_user.username,
                        "content": "",
                    })
                    async for chunk in generate_dm_response_stream(
                        other_user, user, community_name, community_description, ctx_msgs,
                        db=db,
                        community_ids=[str(c.id) for c in user_communities],
                        community_location=community_location,
                    ):
                        chunks.append(chunk)
                        await dm_manager.broadcast(room_id, {
                            "type": "stream_chunk",
                            "sender_id": str(other_user.id),
                            "sender_username": other_user.username,
                            "content": chunk,
                        })
                    ai_text, _ = validate_output("".join(chunks), max_length=300)
                    ai_msg = DirectMessage(
                        sender_id=other_user.id,
                        receiver_id=user.id,
                        content=ai_text,
                    )
                    db.add(ai_msg)
                    await db.commit()
                    await db.refresh(ai_msg)
                    await dm_manager.broadcast(room_id, {
                        "type": "stream_end",
                        "id": str(ai_msg.id),
                        "sender_id": str(other_user.id),
                        "sender_username": other_user.username,
                        "content": ai_text,
                        "created_at": ai_msg.created_at.isoformat(),
                    })
                except Exception:
                    logger.exception("Digital member DM reply failed")

    except WebSocketDisconnect:
        dm_manager.disconnect(websocket, room_id)

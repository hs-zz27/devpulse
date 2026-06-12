import asyncio
import json
import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
import redis.asyncio as aioredis

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.database import get_db
from app.core.rate_limit import UserRateLimiter
from app.models.user import User
from app.models.repo import Review, PullRequest, Repository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()
logger = logging.getLogger(__name__)

reviews_rate_limiter = UserRateLimiter(
    max_requests=60,
    window_seconds=60,
    key_prefix="reviews",
)

# The shared dictionary that holds the waiting lines (queues) for connected browsers
_event_queues: dict[str, asyncio.Queue] = {}

# the background task
async def listen_to_redis_pubsub():
    """
    Listens to the 'devpulse:sse_events' channel and routes messages to user queues. 
    Runs forever in background
    """
    redis_client = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("devpulse:sse_events")
    logger.info("📡 Subscribed to Redis channel: devpulse:sse_events")

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    user_id = str(data.get("user_id"))
                    queue = _event_queues.get(user_id)
                    if queue:
                        await queue.put(data)

                except json.JSONDecodeError:
                    logger.error("Failed to decode Redis pubsub message")
                    
    except asyncio.CancelledError:
        logger.info("Redis listener task cancelled.")
    finally:
        await pubsub.unsubscribe("devpulse:sse_events")
        await redis_client.aclose()


@router.get("/stream", dependencies=[Depends(reviews_rate_limiter)])
async def review_event_stream(request: Request, current_user: User = Depends(get_current_user)):
    """
    SSE Endpoint. The frontend connects here to listen for live updates.
    """
    user_id = str(current_user.id)
    queue: asyncio.Queue = asyncio.Queue()
    _event_queues[user_id] = queue

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event)}\n\n"
                #so that the firewall doesnt close the connection
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            _event_queues.pop(user_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )

@router.get("/", dependencies=[Depends(reviews_rate_limiter)])
async def get_recent_reviews(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Fetch the most recent reviews for the current user's repositories."""
    stmt = (
        select(Review, PullRequest.number, PullRequest.title)
        .join(PullRequest, Review.pr_id == PullRequest.id)
        .join(Repository, PullRequest.repo_id == Repository.id)
        .where(Repository.owner_id == current_user.id)
        .order_by(Review.completed_at.desc())
        .limit(50)
    )
    
    result = await db.execute(stmt)
    rows = result.all()
    
    return [
        {
            "id": r.id,
            "pr_id": r.pr_id,
            "pr_number": pr_number,
            "pr_title": pr_title,
            "status": r.status,
            "risk_score": r.risk_score,
            "summary": r.summary,
            "completed_at": r.completed_at
        }
        for r, pr_number, pr_title in rows
    ]

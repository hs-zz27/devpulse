import logging
import uuid
import redis.asyncio as redis
from redis.exceptions import ResponseError

from app.core.config import settings


logger = logging.getLogger(__name__)

async def init_redis_pool():
    return redis.from_url(
        settings.REDIS_URL, 
        decode_responses=True
    )

async def create_consumer_group():
    redis_client = await init_redis_pool()
    try:
        await redis_client.xgroup_create(
            "devpulse:pr_review_queue",
            "devpulse_workers",
            id="$",
            mkstream=True
        )
    except ResponseError as e:
        if "BUSYGROUP" not in str(e):
            logger.error(f"Failed to create a Consumer group: {e}")
            raise e
    finally:
        await redis_client.aclose()

async def enqueue_pr_review(pr_id: uuid.UUID):
    redis_client = await init_redis_pool()
    try:
        payload = {"type": "pr_review", "pr_id": str(pr_id)}
        await redis_client.xadd(
            "devpulse:pr_review_queue",
            payload,
        )
        logger.info("PR #%s successfully enqueued for review", pr_id)
    except Exception as e:
        logger.error("Failed to enqueue PR #%s to Redis: %s", pr_id, e)
    finally:
        await redis_client.aclose()

    




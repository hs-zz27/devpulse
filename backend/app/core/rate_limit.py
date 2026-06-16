from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis

from app.api.producer import init_redis_pool
from app.core.deps import get_current_user
from app.models.user import User


class RateLimiter:
    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        key_prefix: str,
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.key_prefix = key_prefix

    async def hit(
        self,
        redis_client: Redis,
        identity: str,
    ) -> None:
        key = f"rate_limit:{self.key_prefix}:{identity}"

        current = await redis_client.incr(key)

        if current == 1:
            await redis_client.expire(key, self.window_seconds)

        if current > self.max_requests:
            ttl = await redis_client.ttl(key)

            # Redis TTL special values:
            # -1 = key exists but has no expiry
            # -2 = key does not exist
            if ttl < 0:
                ttl = self.window_seconds

            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": "Too many requests. Please try again later.",
                    "retry_after_seconds": ttl,
                },
                headers={
                    "Retry-After": str(ttl),
                },
            )


def get_client_ip(request: Request) -> str:

    forwarded_for = request.headers.get("x-forwarded-for")

    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    if request.client:
        return request.client.host

    return "unknown"


class UserRateLimiter(RateLimiter):
    """
    Use this for:
    - chat.py
    - metrics.py
    - repos.py
    - reviews.py
    - users.py
    - any endpoint that requires login
    """

    async def __call__(
        self,
        redis_client: Redis = Depends(init_redis_pool),
        current_user: User = Depends(get_current_user),
    ) -> None:
        await self.hit(
            redis_client=redis_client,
            identity=f"user:{current_user.id}",
        )


class IPRateLimiter(RateLimiter):
    """
    Use this for:
    - signup
    - public endpoints
    - unauthenticated routes
    - basic webhook protection
    """

    async def __call__(
        self,
        request: Request,
        redis_client: Redis = Depends(init_redis_pool),
    ) -> None:
        client_ip = get_client_ip(request)

        await self.hit(
            redis_client=redis_client,
            identity=f"ip:{client_ip}",
        )


class UserAndIPRateLimiter(RateLimiter):
    """
    Example use:
    - very expensive AI endpoint
    - export/report generation endpoint
    """

    async def __call__(
        self,
        request: Request,
        redis_client: Redis = Depends(init_redis_pool),
        current_user: User = Depends(get_current_user),
    ) -> None:
        client_ip = get_client_ip(request)

        await self.hit(
            redis_client=redis_client,
            identity=f"user:{current_user.id}",
        )

        await self.hit(
            redis_client=redis_client,
            identity=f"ip:{client_ip}",
        )

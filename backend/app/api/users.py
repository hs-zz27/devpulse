from fastapi import APIRouter, Depends
from app.core.deps import get_current_user
from app.core.rate_limit import UserRateLimiter
from app.models.user import User

router = APIRouter()

users_rate_limiter = UserRateLimiter(
    max_requests=30,
    window_seconds=60,
    key_prefix="users",
)

@router.get("/users/me", dependencies=[Depends(users_rate_limiter)])
async def get_user(current_user: User = Depends(get_current_user)):
    return current_user

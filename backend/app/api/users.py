from fastapi import APIRouter, Depends
from app.core.deps import get_current_user
from app.models.user import User
router = APIRouter()

@router.get("/users/me")
async def get_user(current_user: User = Depends(get_current_user)):
    return current_user

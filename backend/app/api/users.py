from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
import httpx
from app.core.config import settings
from app.core.database import get_db
from app.core import security
from app.core.deps import get_current_user
from app.models.user import User, OAuthToken
router = APIRouter()

@router.get("/users/me")
async def get_user(current_user: User = Depends(get_current_user)):
    return current_user

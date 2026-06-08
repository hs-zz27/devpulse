from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx
from app.core.config import settings
from app.core.database import get_db
from app.core import security
from app.models.user import User, OAuthToken
router = APIRouter()

@router.get("/login")
async def login_with_github():
    github_auth_url = (f"https://github.com/login/oauth/authorize?client_id={settings.GITHUB_CLIENT_ID}&scope=user:email,repo")
    return RedirectResponse(url=github_auth_url)


@router.get("/callback")
async def github_callback(code: str, db: AsyncSession = Depends(get_db)):
    github_access_token_url="https://github.com/login/oauth/access_token"
    github_user_url="https://api.github.com/user"
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            github_access_token_url,
            data={
                "client_id": settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
                "code": code,
            },
            headers={"Accept": "application/json"}
        )
        token_data = token_response.json()
        github_access_token = token_data.get("access_token")

        if not github_access_token:
            raise HTTPException(status_code=400, detail="GitHub OAuth failed")
        
        profile_response = await client.get(
            github_user_url,
            headers={"Authorization": f"Bearer {github_access_token}"}
        )
        github_user = profile_response.json()

    result = await db.execute(select(User).where(User.github_id == github_user["id"]))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            name=github_user.get("name"),
            github_id=github_user["id"],
            login=github_user.get("login", str(github_user["id"])),
            avatar_url=github_user.get("avatar_url"),
        )
        db.add(user)
        await db.flush()
        
        oauth_token = OAuthToken(
            access_token=github_access_token,
            user_id=user.id,
        )
        db.add(oauth_token)
    else:
        token_result = await db.execute(select(OAuthToken).where(OAuthToken.user_id == user.id))
        existing_token = token_result.scalar_one_or_none()
        if existing_token:
            existing_token.access_token = github_access_token
        else:
            new_token = OAuthToken(
                access_token=github_access_token,
                user_id=user.id,
            )
            db.add(new_token)

    await db.commit()
    await db.refresh(user)

    devpulse_token = security.create_access_token(user_id=str(user.id))
    devpulse_refresh_token = security.create_refresh_token(user_id=str(user.id))

    response = RedirectResponse(url=f"{settings.FRONTEND_URL}/dashboard")
    response.set_cookie(key="access_token", value=devpulse_token, httponly=True, secure=True)
    response.set_cookie(key="refresh_token", value=devpulse_refresh_token, httponly=True, secure=True)

    return response






    

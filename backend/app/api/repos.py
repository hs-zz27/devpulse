from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
import httpx

from app.core.config import settings
from app.core.database import get_db
from app.core import security
from app.core.deps import get_current_user
from app.core.rate_limit import UserRateLimiter
from app.models.repo import Repository
from app.models.user import User, OAuthToken

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

repos_rate_limiter = UserRateLimiter(
    max_requests=30,
    window_seconds=60,
    key_prefix="repos",
)

class ConnectRepoRequest(BaseModel):
    github_repo_id: int
    full_name: str

@router.get("/", dependencies=[Depends(repos_rate_limiter)])
async def get_repos(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Repository).where(Repository.owner_id == current_user.id)
    )
    return result.scalars().all()

@router.get("/github", dependencies=[Depends(repos_rate_limiter)])
async def get_repos_github(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    token_result = await db.execute(
        select(OAuthToken).where(OAuthToken.user_id == current_user.id)
    )
    oauth_token = token_result.scalar_one_or_none()

    if not oauth_token:
        raise HTTPException(status_code=401, detail="GitHub access token not found")

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.github.com/user/repos",
            headers={
                "Authorization": f"Bearer {oauth_token.access_token}",
                "Accept": "application/vnd.github.v3+json",
            },
            params={
                "sort": "updated",
                "per_page": 100,
            },
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Failed to fetch repos from GitHub: {response.text}",
        )

    github_repos = response.json()

    return [
        {
            "id": repo["id"],
            "github_repo_id": repo["id"],
            "name": repo["name"],
            "full_name": repo["full_name"],
            "private": repo["private"],
            "html_url": repo["html_url"],
        }
        for repo in github_repos
    ]

async def register_webhook(full_name: str, webhook_secret: str, access_token: str):
    webhook_url = f"{settings.BASE_URL.rstrip('/')}/webhooks/github"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.github.com/repos/{full_name}/hooks",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github.v3+json",
            },
            json={
                "name": "web",
                "active": True,
                "events": ["pull_request", "push"],
                "config": {
                    "url": webhook_url,
                    "content_type": "json",
                    "secret": webhook_secret,
                },
            },
        )

    if response.status_code not in (200, 201):
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Failed to create webhook on GitHub: {response.text}",
        )

    data = response.json()
    return data.get("id")

async def maybe_register_webhook(full_name: str, webhook_secret: str, access_token: str):
    if settings.BASE_URL.startswith("http://localhost") or settings.BASE_URL.startswith("http://127.0.0.1"):
        return None

    return await register_webhook(
        full_name=full_name,
        webhook_secret=webhook_secret,
        access_token=access_token,
    )

@router.post("/connect", dependencies=[Depends(repos_rate_limiter)])
async def make_connection(
    payload: ConnectRepoRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    token_result = await db.execute(
        select(OAuthToken).where(OAuthToken.user_id == current_user.id)
    )
    oauth_token = token_result.scalar_one_or_none()

    if not oauth_token:
        raise HTTPException(status_code=401, detail="GitHub access token not found")

    result = await db.execute(
        select(Repository).where(
            Repository.github_repo_id == payload.github_repo_id,
            Repository.owner_id == current_user.id,
        )
    )
    repo = result.scalar_one_or_none()

    if repo is None:
        repo = Repository(
            owner_id=current_user.id,
            github_repo_id=payload.github_repo_id,
            full_name=payload.full_name,
            webhook_id=None,
            webhook_secret=None,
            is_active=True,
        )
        db.add(repo)
        await db.flush()
    else:
        repo.full_name = payload.full_name
        repo.is_active = True

    webhook_secret = security.generate_webhook_secret()

    webhook_id = await maybe_register_webhook(
        full_name=payload.full_name,
        webhook_secret=webhook_secret,
        access_token=oauth_token.access_token,
    )

    repo.webhook_id = webhook_id
    repo.webhook_secret = webhook_secret
    repo.is_active = True

    db.add(repo)
    await db.commit()
    await db.refresh(repo)

    return repo

import logging
from uuid import UUID

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
from app.core.circuit_breaker import github_circuit_breaker, CircuitBreakerOpenError
from app.core.github_http import github_get, github_post, github_status_to_http_exception

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.github_pr_sync import sync_repository_pull_requests

logger = logging.getLogger(__name__)

router = APIRouter()

class PullRequestSyncResponse(BaseModel):
    fetched_count: int
    inserted_count: int
    updated_count: int
    skipped_count: int = 0

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
        try:
            response = await github_circuit_breaker.call(
                github_get,
                client,
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
        except CircuitBreakerOpenError as exc:
            raise HTTPException(
                status_code=503,
                detail="GitHub is temporarily unavailable. Please try again later.",
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise github_status_to_http_exception(
                exc,
                "Failed to fetch repos from GitHub",
            ) from exc

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
        try:
            response = await github_circuit_breaker.call(
                github_post,
                client,
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
        except CircuitBreakerOpenError as exc:
            raise HTTPException(
                status_code=503,
                detail="GitHub is temporarily unavailable. Please try again later.",
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise github_status_to_http_exception(
                exc,
                "Failed to create webhook on GitHub",
            ) from exc

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

    try:
        sync_result = await sync_repository_pull_requests(
            db=db,
            repo=repo,
            github_token=oauth_token.access_token,
            full=True,
        )
        logger.info(
            "Auto PR sync after repo connect succeeded | repo=%s | result=%s",
            repo.full_name,
            sync_result.as_dict(),
        )
    except Exception:
        logger.exception(
            "Auto PR sync after repo connect failed | repo=%s",
            repo.full_name,
        )

    return repo

@router.post("/{repo_id}/sync-prs", response_model=PullRequestSyncResponse, dependencies=[Depends(repos_rate_limiter)])
async def sync_repo_pull_requests(
    repo_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PullRequestSyncResponse:
    repo_result = await db.execute(
        select(Repository).where(
            Repository.id == repo_id,
            Repository.owner_id == current_user.id,
        )
    )
    repo = repo_result.scalar_one_or_none()

    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    token_result = await db.execute(
        select(OAuthToken).where(OAuthToken.user_id == current_user.id)
    )
    oauth_token = token_result.scalar_one_or_none()

    if not oauth_token:
        raise HTTPException(status_code=401, detail="GitHub access token not found")

    sync_result = await sync_repository_pull_requests(
        db=db,
        repo=repo,
        github_token=oauth_token.access_token,
        full=False,
    )

    return PullRequestSyncResponse(**sync_result.as_dict())

import secrets
from urllib.parse import urlencode
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import IPRateLimiter
from app.models.user import OAuthToken, User
from app.core.circuit_breaker import github_circuit_breaker, CircuitBreakerOpenError
from app.core.github_http import github_get, github_post, github_status_to_http_exception



router = APIRouter()


login_limiter = IPRateLimiter(
    max_requests=20,
    window_seconds=60,
    key_prefix="auth_login",
)

callback_limiter = IPRateLimiter(
    max_requests=10,
    window_seconds=60,
    key_prefix="auth_callback",
)


COOKIE_SECURE = settings.ENVIRONMENT == "production"
COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"
COOKIE_PATH = "/"

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"


def build_github_auth_url(state: str) -> str:
    """
    Build the GitHub OAuth URL safely.

    Beginner explanation:
    - GitHub needs query parameters like client_id, scope, and state.
    - urlencode() safely converts a Python dict into URL query string format.
    - This is better than manually joining strings with &.
    """

    params = urlencode(
        {
            "client_id": settings.GITHUB_CLIENT_ID,
            "scope": "user:email,repo",
            "state": state,
        }
    )

    return f"{GITHUB_AUTHORIZE_URL}?{params}"








def parse_github_json(
    response: httpx.Response,
    detail: str,
) -> dict:
    """
    Parse GitHub JSON safely.

    Why this matters:
    - response.json() can fail if GitHub returns invalid JSON.
    - That is rare, but production code should handle it.
    """

    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=detail,
        ) from exc

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=502,
            detail=detail,
        )

    return data


@router.get("/login", dependencies=[Depends(login_limiter)])
async def login_with_github():
    """
    Start GitHub OAuth login.

    What happens here:
    1. Create a random state.
    2. Store the state in an HttpOnly cookie.
    3. Redirect the browser to GitHub.

    The state protects against OAuth CSRF/login injection.
    """

    state = secrets.token_urlsafe(32)
    github_auth_url = build_github_auth_url(state)

    response = RedirectResponse(url=github_auth_url)
    response.set_cookie(
        key="oauth_state",
        value=state,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=300,
        path=COOKIE_PATH,
    )

    return response


@router.get("/callback", dependencies=[Depends(callback_limiter)])
async def github_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Finish GitHub OAuth login.

    GitHub redirects here with:
    - code: temporary code used to get access token
    - state: value that must match our oauth_state cookie
    """

    if not code or not state:
        raise HTTPException(
            status_code=400,
            detail="Missing OAuth code or state",
        )

    stored_state = request.cookies.get("oauth_state")

    if not stored_state or not secrets.compare_digest(stored_state, state):
        raise HTTPException(
            status_code=400,
            detail="Invalid OAuth state",
        )

    timeout = httpx.Timeout(10.0, connect=5.0)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                token_response = await github_circuit_breaker.call(
                    github_post,
                    client,
                    GITHUB_ACCESS_TOKEN_URL,
                    data={
                        "client_id": settings.GITHUB_CLIENT_ID,
                        "client_secret": settings.GITHUB_CLIENT_SECRET,
                        "code": code,
                    },
                    headers={
                        "Accept": "application/json",
                    },
                )
            except httpx.HTTPStatusError as exc:
                raise github_status_to_http_exception(
                    exc,
                    "GitHub token exchange failed",
                ) from exc

            token_data = parse_github_json(
                token_response,
                "Invalid GitHub token response",
            )

            github_access_token = token_data.get("access_token")

            if not github_access_token:
                raise HTTPException(
                    status_code=400,
                    detail="GitHub OAuth failed",
                )

            try:
                profile_response = await github_circuit_breaker.call(
                    github_get,
                    client,
                    GITHUB_USER_URL,
                    headers={
                        "Authorization": f"Bearer {github_access_token}",
                        "Accept": "application/json",
                    },
                )
            except httpx.HTTPStatusError as exc:
                raise github_status_to_http_exception(
                    exc,
                    "GitHub profile fetch failed",
                ) from exc

            github_user = parse_github_json(
                profile_response,
                "Invalid GitHub profile response",
            )

    except CircuitBreakerOpenError as exc:
        raise HTTPException(
            status_code=503,
            detail="GitHub is temporarily unavailable. Please try again later.",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not connect to GitHub",
        ) from exc

    github_id = github_user.get("id")

    if not github_id:
        raise HTTPException(
            status_code=400,
            detail="Invalid GitHub profile",
        )

    result = await db.execute(
        select(User).where(User.github_id == github_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            name=github_user.get("name"),
            github_id=github_id,
            login=github_user.get("login", str(github_id)),
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
        token_result = await db.execute(
            select(OAuthToken).where(OAuthToken.user_id == user.id)
        )
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

    response.delete_cookie(
        key="oauth_state",
        path=COOKIE_PATH,
    )

    response.set_cookie(
        key="access_token",
        value=devpulse_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path=COOKIE_PATH,
    )

    response.set_cookie(
        key="refresh_token",
        value=devpulse_refresh_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path=COOKIE_PATH,
    )

    return response
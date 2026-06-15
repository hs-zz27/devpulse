import httpx
from fastapi import HTTPException
from typing import Any

async def github_post(client: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
    response = await client.post(url, **kwargs)
    response.raise_for_status()
    return response

async def github_get(client: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
    response = await client.get(url, **kwargs)
    response.raise_for_status()
    return response


def github_status_to_http_exception(
    exc: httpx.HTTPStatusError,
    detail: str,
) -> HTTPException:
    status_code = exc.response.status_code

    if status_code == 429:
        return HTTPException(
            status_code=503,
            detail="GitHub is rate limiting requests. Please try again later.",
        )

    if status_code >= 500:
        return HTTPException(
            status_code=502,
            detail=detail,
        )

    return HTTPException(
        status_code=400,
        detail=detail,
    )

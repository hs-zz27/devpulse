from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repo import Repository, PullRequest
from app.models.enums import PRState

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
PER_PAGE = 100

@dataclass(slots=True)
class PullRequestSyncResult:
    fetched_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "fetched_count": self.fetched_count,
            "inserted_count": self.inserted_count,
            "updated_count": self.updated_count,
            "skipped_count": self.skipped_count,
        }

def parse_github_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed
    except ValueError:
        logger.warning("Unable to parse GitHub datetime: %s", value)
        return None

def normalize_pr_state(pr: dict[str, Any]) -> PRState:
    """
    GitHub represents merged PRs as:
    - state = closed
    - merged = true

    Locally, that should become PRState.MERGED.
    """

    if pr.get("merged") is True:
        return PRState.MERGED

    github_state = str(pr.get("state", "")).lower()

    if github_state == "closed":
        return PRState.CLOSED

    return PRState.OPEN

def has_migration_files(files: list[dict[str, Any]]) -> bool:
    for file_info in files:
        filename = str(file_info.get("filename", "")).lower()

        if "migration" in filename:
            return True

        if "/migrations/" in filename or filename.startswith("migrations/"):
            return True

        if filename.endswith(".sql") and "migrate" in filename:
            return True

    return False

async def github_get(
    client: httpx.AsyncClient,
    token: str,
    path: str,
    params: dict[str, Any] | None = None,
) -> Any:
    response = await client.get(
        f"{GITHUB_API_BASE}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        params=params,
    )

    if response.status_code >= 400:
        logger.error(
            "GitHub API request failed | path=%s | status=%s | body=%s",
            path,
            response.status_code,
            response.text[:2000],
        )
        response.raise_for_status()

    return response.json()

async def fetch_all_pull_requests(
    client: httpx.AsyncClient,
    token: str,
    owner: str,
    repo_name: str,
) -> list[dict[str, Any]]:
    all_prs: list[dict[str, Any]] = []
    page = 1

    while True:
        prs = await github_get(
            client,
            token,
            f"/repos/{owner}/{repo_name}/pulls",
            params={
                "state": "all",
                "per_page": PER_PAGE,
                "page": page,
                "sort": "updated",
                "direction": "desc",
            },
        )

        if not prs:
            break

        all_prs.extend(prs)

        if len(prs) < PER_PAGE:
            break

        page += 1

    return all_prs

async def fetch_pull_request_detail(
    client: httpx.AsyncClient,
    token: str,
    owner: str,
    repo_name: str,
    number: int,
) -> dict[str, Any]:
    return await github_get(
        client,
        token,
        f"/repos/{owner}/{repo_name}/pulls/{number}",
    )

async def fetch_pull_request_files(
    client: httpx.AsyncClient,
    token: str,
    owner: str,
    repo_name: str,
    number: int,
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    page = 1

    while True:
        batch = await github_get(
            client,
            token,
            f"/repos/{owner}/{repo_name}/pulls/{number}/files",
            params={
                "per_page": PER_PAGE,
                "page": page,
            },
        )

        if not batch:
            break

        files.extend(batch)

        if len(batch) < PER_PAGE:
            break

        page += 1

    return files

async def upsert_pull_request_from_github(
    db: AsyncSession,
    repo: Repository,
    pr: dict[str, Any],
    *,
    files: list[dict[str, Any]] | None = None,
) -> str:
    """
    Returns:
    - inserted
    - updated
    - skipped
    """

    github_pr_id = pr.get("id")
    number = pr.get("number")

    if github_pr_id is None or number is None:
        logger.warning("Skipping PR without id or number | repo=%s", repo.full_name)
        return "skipped"

    normalized_state = normalize_pr_state(pr)
    merged_at = parse_github_datetime(pr.get("merged_at"))

    if normalized_state != PRState.MERGED:
        merged_at = None

    opened_at = parse_github_datetime(pr.get("created_at"))

    author = pr.get("user") or {}
    author_login = author.get("login") or "unknown"

    if files is None:
        files = []

    existing_result = await db.execute(
        select(PullRequest).where(
            PullRequest.repo_id == repo.id,
            PullRequest.github_pr_id == github_pr_id,
        )
    )
    existing = existing_result.scalar_one_or_none()

    values = {
        "repo_id": repo.id,
        "github_pr_id": github_pr_id,
        "number": int(number),
        "title": pr.get("title") or "Untitled pull request",
        "author_login": author_login,
        "state": normalized_state,
        "opened_at": opened_at,
        "merged_at": merged_at,
        "lines_added": int(pr.get("additions") or 0),
        "lines_removed": int(pr.get("deletions") or 0),
        "files_changed": int(pr.get("changed_files") or len(files) or 0),
        "has_migrations": has_migration_files(files),
    }

    logger.info(
        "Syncing PR | repo=%s | number=%s | github_state=%s | merged=%s | normalized_state=%s | merged_at=%s",
        repo.full_name,
        number,
        pr.get("state"),
        pr.get("merged"),
        normalized_state,
        merged_at,
    )

    if existing is None:
        db.add(PullRequest(**values))
        return "inserted"

    for key, value in values.items():
        setattr(existing, key, value)

    return "updated"

async def sync_repository_pull_requests(
    db: AsyncSession,
    repo: Repository,
    github_token: str,
) -> PullRequestSyncResult:
    """
    Fetch all historical PRs for one repository from GitHub and upsert them locally.

    Used by:
    - automatic sync after repo connect
    - manual Sync now button
    - repair/backfill endpoint
    """

    if "/" not in repo.full_name:
        raise ValueError(f"Invalid repository full_name: {repo.full_name}")

    owner, repo_name = repo.full_name.split("/", 1)
    result = PullRequestSyncResult()

    async with httpx.AsyncClient(timeout=60.0) as client:
        prs = await fetch_all_pull_requests(client, github_token, owner, repo_name)
        result.fetched_count = len(prs)

        for pr in prs:
            number = int(pr["number"])

            # The list endpoint may omit additions/deletions/changed_files.
            # Fetch detail for accurate metrics.
            detail = await fetch_pull_request_detail(
                client,
                github_token,
                owner,
                repo_name,
                number,
            )
            files = await fetch_pull_request_files(
                client,
                github_token,
                owner,
                repo_name,
                number,
            )

            status = await upsert_pull_request_from_github(
                db=db,
                repo=repo,
                pr=detail,
                files=files,
            )

            if status == "inserted":
                result.inserted_count += 1
            elif status == "updated":
                result.updated_count += 1
            else:
                result.skipped_count += 1

    await db.commit()

    logger.info(
        "Completed PR sync | repo=%s | fetched=%s | inserted=%s | updated=%s | skipped=%s",
        repo.full_name,
        result.fetched_count,
        result.inserted_count,
        result.updated_count,
        result.skipped_count,
    )

    return result

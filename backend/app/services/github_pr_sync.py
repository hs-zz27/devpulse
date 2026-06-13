from __future__ import annotations

import asyncio
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
GITHUB_API_VERSION = "2022-11-28"
PER_PAGE = 100
MAX_CONCURRENT_GITHUB_REQUESTS = 8

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

def github_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
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
    github_state = str(pr.get("state") or "").lower()

    if github_state == "closed" and pr.get("merged") is True:
        return PRState.MERGED

    if github_state == "closed" and pr.get("merged_at"):
        return PRState.MERGED

    if github_state == "closed":
        return PRState.CLOSED

    if github_state == "open":
        return PRState.OPEN

    logger.warning(
        "Unknown GitHub PR state. Falling back to CLOSED | state=%s | merged=%s | merged_at=%s",
        pr.get("state"),
        pr.get("merged"),
        pr.get("merged_at"),
    )
    return PRState.CLOSED

def has_migration_files(files: list[dict[str, Any]]) -> bool:
    for file_info in files:
        filename = str(file_info.get("filename") or "").lower()

        if filename.endswith(".sql"):
            return True

        if "migration" in filename:
            return True

        if "/migrations/" in filename or filename.startswith("migrations/"):
            return True

        if "alembic/versions/" in filename:
            return True

    return False

async def github_get(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, Any] | None = None,
) -> Any:
    response = await client.get(path, params=params)

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
    owner: str,
    repo_name: str,
    *,
    stop_after_unchanged: bool,
    existing_by_github_id: dict[int, PullRequest],
) -> list[dict[str, Any]]:
    all_prs: list[dict[str, Any]] = []
    page = 1

    while True:
        prs = await github_get(
            client,
            f"/repos/{owner}/{repo_name}/pulls",
            params={
                "state": "all",
                "per_page": PER_PAGE,
                "page": page,
                "sort": "updated",
                "direction": "desc",
            },
        )

        if not isinstance(prs, list):
            logger.warning(
                "Unexpected GitHub PR list response | repo=%s/%s | page=%s",
                owner,
                repo_name,
                page,
            )
            break

        if not prs:
            break

        all_prs.extend(prs)

        if stop_after_unchanged:
            page_has_only_unchanged_existing_prs = True

            for pr in prs:
                github_pr_id = pr.get("id")
                github_updated_at = parse_github_datetime(pr.get("updated_at"))

                existing = (
                    existing_by_github_id.get(int(github_pr_id))
                    if github_pr_id is not None
                    else None
                )

                existing_updated_at = (
                    getattr(existing, "github_updated_at", None)
                    or getattr(existing, "updated_at", None)
                    if existing is not None
                    else None
                )

                if existing is None or not github_updated_at or not existing_updated_at:
                    page_has_only_unchanged_existing_prs = False
                    break

                if github_updated_at > existing_updated_at:
                    page_has_only_unchanged_existing_prs = False
                    break

            if page_has_only_unchanged_existing_prs:
                break

        if len(prs) < PER_PAGE:
            break

        page += 1

    return all_prs

async def fetch_pull_request_detail(
    client: httpx.AsyncClient,
    owner: str,
    repo_name: str,
    number: int,
) -> dict[str, Any]:
    detail = await github_get(
        client,
        f"/repos/{owner}/{repo_name}/pulls/{number}",
    )

    if not isinstance(detail, dict):
        raise ValueError(f"Unexpected GitHub PR detail response for PR #{number}")

    return detail

async def fetch_pull_request_files(
    client: httpx.AsyncClient,
    owner: str,
    repo_name: str,
    number: int,
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    page = 1

    while True:
        batch = await github_get(
            client,
            f"/repos/{owner}/{repo_name}/pulls/{number}/files",
            params={
                "per_page": PER_PAGE,
                "page": page,
            },
        )

        if not isinstance(batch, list):
            logger.warning(
                "Unexpected GitHub PR files response | repo=%s/%s | number=%s | page=%s",
                owner,
                repo_name,
                number,
                page,
            )
            break

        if not batch:
            break

        files.extend(batch)

        if len(batch) < PER_PAGE:
            break

        page += 1

    return files

def pr_needs_detail_or_files(
    existing: PullRequest | None,
    list_pr: dict[str, Any],
    *,
    full: bool,
) -> bool:
    if existing is None:
        return True

    if full:
        return True

    github_updated_at = parse_github_datetime(list_pr.get("updated_at"))

    existing_updated_at = (
        getattr(existing, "github_updated_at", None)
        or getattr(existing, "updated_at", None)
    )

    if github_updated_at and existing_updated_at and github_updated_at > existing_updated_at:
        return True

    if getattr(existing, "lines_added", None) is None:
        return True

    if getattr(existing, "lines_removed", None) is None:
        return True

    if getattr(existing, "files_changed", None) is None:
        return True

    if getattr(existing, "has_migrations", None) is None:
        return True

    return False

async def upsert_pull_request_from_github(
    db: AsyncSession,
    repo: Repository,
    pr: dict[str, Any],
    *,
    existing: PullRequest | None,
    files: list[dict[str, Any]] | None = None,
) -> str:
    github_pr_id = pr.get("id")
    number = pr.get("number")

    if github_pr_id is None or number is None:
        logger.warning("Skipping PR without id or number | repo=%s", repo.full_name)
        return "skipped"

    github_pr_id = int(github_pr_id)
    number = int(number)

    normalized_state = normalize_pr_state(pr)
    merged_at = parse_github_datetime(pr.get("merged_at"))

    if normalized_state != PRState.MERGED:
        merged_at = None

    opened_at = parse_github_datetime(pr.get("created_at"))
    github_updated_at = parse_github_datetime(pr.get("updated_at"))

    author = pr.get("user") or {}
    author_login = author.get("login") or "unknown"

    files = files or []

    values = {
        "repo_id": repo.id,
        "github_pr_id": github_pr_id,
        "number": number,
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

    if existing is not None and hasattr(existing, "github_updated_at"):
        values["github_updated_at"] = github_updated_at

    if existing is None:
        db.add(PullRequest(**values))
        return "inserted"

    changed = False

    for key, value in values.items():
        if hasattr(existing, key) and getattr(existing, key) != value:
            setattr(existing, key, value)
            changed = True

    return "updated" if changed else "skipped"

async def sync_repository_pull_requests(
    db: AsyncSession,
    repo: Repository,
    github_token: str,
    *,
    full: bool = False,
) -> PullRequestSyncResult:
    """
    Optimized PR sync.

    full=True:
    - use for first repo connect or repair backfill

    full=False:
    - use for normal Sync now
    - skips unchanged PRs
    - avoids unnecessary detail/files calls
    """

    if "/" not in repo.full_name:
        raise ValueError(f"Invalid repository full_name: {repo.full_name}")

    owner, repo_name = repo.full_name.split("/", 1)
    result = PullRequestSyncResult()

    existing_result = await db.execute(
        select(PullRequest).where(PullRequest.repo_id == repo.id)
    )
    existing_prs = list(existing_result.scalars().all())

    existing_by_github_id = {
        int(pr.github_pr_id): pr
        for pr in existing_prs
        if pr.github_pr_id is not None
    }

    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
    limits = httpx.Limits(max_connections=16, max_keepalive_connections=8)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_GITHUB_REQUESTS)

    async with httpx.AsyncClient(
        base_url=GITHUB_API_BASE,
        headers=github_headers(github_token),
        timeout=timeout,
        limits=limits,
    ) as client:
        prs = await fetch_all_pull_requests(
            client,
            owner,
            repo_name,
            stop_after_unchanged=not full,
            existing_by_github_id=existing_by_github_id,
        )

        result.fetched_count = len(prs)

        async def process_pr(pr_summary: dict[str, Any]) -> str:
            try:
                github_pr_id = pr_summary.get("id")
                number = int(pr_summary["number"])

                existing = (
                    existing_by_github_id.get(int(github_pr_id))
                    if github_pr_id is not None
                    else None
                )

                if not pr_needs_detail_or_files(existing, pr_summary, full=full):
                    return await upsert_pull_request_from_github(
                        db=db,
                        repo=repo,
                        pr=pr_summary,
                        existing=existing,
                        files=[],
                    )

                async with semaphore:
                    detail = await fetch_pull_request_detail(
                        client,
                        owner,
                        repo_name,
                        number,
                    )

                try:
                    async with semaphore:
                        files = await fetch_pull_request_files(
                            client,
                            owner,
                            repo_name,
                            number,
                        )
                except httpx.HTTPError:
                    logger.exception(
                        "Unable to fetch PR files. Continuing without file metadata | repo=%s | number=%s",
                        repo.full_name,
                        number,
                    )
                    files = []

                return await upsert_pull_request_from_github(
                    db=db,
                    repo=repo,
                    pr=detail,
                    existing=existing,
                    files=files,
                )

            except Exception:
                logger.exception(
                    "Skipping PR during sync due to error | repo=%s | pr=%s",
                    repo.full_name,
                    pr_summary,
                )
                return "skipped"

        statuses = await asyncio.gather(*(process_pr(pr) for pr in prs))

        for status in statuses:
            if status == "inserted":
                result.inserted_count += 1
            elif status == "updated":
                result.updated_count += 1
            else:
                result.skipped_count += 1

    await db.commit()

    logger.info(
        "Completed PR sync | repo=%s | full=%s | fetched=%s | inserted=%s | updated=%s | skipped=%s",
        repo.full_name,
        full,
        result.fetched_count,
        result.inserted_count,
        result.updated_count,
        result.skipped_count,
    )

    return result

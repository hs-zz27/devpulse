"""
In-process worker runner for DevPulse.

Same review-processing logic as worker/main.py, packaged so it can run as an
asyncio task INSIDE the FastAPI process. This lets the free Render web service
also drain the Redis review queue without paying for a separate Background
Worker.

Differences vs worker/main.py:
- No sys.path hack: this lives inside `backend`, so `app.*` imports work.
- No start_http_server(9001): metrics live in the same process as the API,
  so they are already exposed by the API's GET /metrics endpoint.
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone

from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.agent.loop import run_agent, calc_review_issue_risk_score
from app.api.producer import init_redis_pool
from app.core.database import AsyncSessionLocal
from app.models.enums import PRCategory, PRSeverity, ReviewStatus
from app.models.repo import PullRequest, Repository, Review, ReviewIssue
from app.models.user import User
from app.api.metrics import REVIEW_DURATION_SECONDS, REVIEWS_COMPLETED_TOTAL

logger = logging.getLogger(__name__)

CONSUMER_NAME = f"inproc-worker-{os.getpid()}"
STREAM_NAME = "devpulse:pr_review_queue"
GROUP_NAME = "devpulse_workers"
MAX_REVIEW_ATTEMPTS = 3
RETRY_IDLE_MS = 10 * 60 * 1000

pending_start_id = "0-0"


async def claim_and_process_pending(redis_client):
    global pending_start_id
    try:
        claimed = await redis_client.xautoclaim(
            name=STREAM_NAME,
            groupname=GROUP_NAME,
            consumername=CONSUMER_NAME,
            min_idle_time=RETRY_IDLE_MS,
            start_id=pending_start_id,
            count=1,
        )
    except RedisConnectionError as e:
        logger.error("Redis connection error: %s. Retrying in 5s...", e)
        return

    if len(claimed) == 3:
        next_start_id, claimed_messages, _deleted_ids = claimed
    else:
        next_start_id, claimed_messages = claimed

    pending_start_id = next_start_id

    for message_id, payload in claimed_messages:
        logger.info("Reclaimed pending message %s for retry", message_id)
        await process_review_message(
            redis_client=redis_client,
            message_id=message_id,
            payload=payload,
            is_retry=True,
        )


async def process_review_message(redis_client, message_id, payload, is_retry):
    pr_id = payload.get("pr_id")
    pr_commit_sha = payload.get("commit_sha")
    if not pr_id or not pr_commit_sha:
        logger.error(
            "Malformed message (missing pr_id or commit_sha), acking and skipping. Payload: %s",
            payload,
        )
        await redis_client.xack(STREAM_NAME, GROUP_NAME, message_id)
        return

    logger.info("Received PR ID: %s retry=%s", pr_id, is_retry)

    review_id = None
    repo_full_name = None
    pr_number = None
    github_token = None
    owner_id = None

    # PHASE 1: DB claim/setup only
    async with AsyncSessionLocal() as db_session:
        if not is_retry:
            review = Review(
                pr_id=pr_id,
                status=ReviewStatus.IN_PROGRESS,
                commit_sha=pr_commit_sha,
                attempt_count=1,
                started_at=datetime.now(timezone.utc),
            )
            db_session.add(review)
            try:
                await db_session.commit()
                await db_session.refresh(review)
            except IntegrityError:
                await db_session.rollback()
                logger.info(
                    "Review already exists for PR %s commit %s, acking duplicate message",
                    pr_id,
                    pr_commit_sha,
                )
                await redis_client.xack(STREAM_NAME, GROUP_NAME, message_id)
                return
        else:
            review_stmt = select(Review).where(
                Review.pr_id == pr_id,
                Review.commit_sha == pr_commit_sha,
            )
            review_result = await db_session.execute(review_stmt)
            review = review_result.scalars().first()
            if not review:
                logger.error(
                    "Review not found for PR %s commit %s, acking and skipping",
                    pr_id,
                    pr_commit_sha,
                )
                await redis_client.xack(STREAM_NAME, GROUP_NAME, message_id)
                return
            if review.status == ReviewStatus.COMPLETED:
                logger.info(
                    "Review %s already completed, acking pending message", review.id
                )
                await redis_client.xack(STREAM_NAME, GROUP_NAME, message_id)
                return
            if review.attempt_count >= MAX_REVIEW_ATTEMPTS:
                logger.error(
                    "Review %s exceeded max attempts (%s), marking as failed and removing from queue",
                    review.id,
                    MAX_REVIEW_ATTEMPTS,
                )
                REVIEWS_COMPLETED_TOTAL.labels(status="failed").inc()
                review.status = ReviewStatus.FAILED
                review.completed_at = datetime.now(timezone.utc)
                await db_session.commit()
                await redis_client.xack(STREAM_NAME, GROUP_NAME, message_id)
                return

            review.status = ReviewStatus.IN_PROGRESS
            review.attempt_count += 1
            review.started_at = datetime.now(timezone.utc)
            await db_session.commit()
            await db_session.refresh(review)

        # Load PR + Repository + OAuth token from the DB
        stmt = (
            select(PullRequest)
            .options(
                selectinload(PullRequest.repository)
                .selectinload(Repository.owner)
                .selectinload(User.oauth_token)
            )
            .where(PullRequest.id == pr_id)
        )
        pr_result = await db_session.execute(stmt)
        pr = pr_result.scalars().first()
        if not pr:
            logger.error(
                "PR with id %s not found in database, acking and skipping", pr_id
            )
            await redis_client.xack(STREAM_NAME, GROUP_NAME, message_id)
            return

        repo = pr.repository
        oauth = repo.owner.oauth_token if repo and repo.owner else None
        if not oauth or not oauth.access_token:
            logger.error(
                "No OAuth token available for repo owner (repo=%s), acking and skipping",
                repo.full_name if repo else "unknown",
            )
            await redis_client.xack(STREAM_NAME, GROUP_NAME, message_id)
            return

        # Copy plain values before closing DB session
        review_id = review.id
        repo_full_name = repo.full_name
        pr_number = pr.number
        owner_id = repo.owner_id
        github_token = oauth.access_token

    # PHASE 2: Run AI outside DB session
    review_started_at = time.perf_counter()
    pr_data = {
        "repo_full_name": repo_full_name,
        "pr_number": pr_number,
        "pr_id": str(pr_id),
        "commit_sha": pr_commit_sha,
    }
    try:
        agent_result = await run_agent(
            github_token=github_token,
            pr_data=pr_data,
        )
    except Exception as e:
        logger.exception("Agent failed for PR %s: %s", pr_id, e)
        REVIEWS_COMPLETED_TOTAL.labels(status="failed").inc()
        REVIEW_DURATION_SECONDS.labels(status="failed").observe(
            time.perf_counter() - review_started_at
        )
        async with AsyncSessionLocal() as db_session:
            review = await db_session.get(Review, review_id)
            if review:
                review.status = ReviewStatus.FAILED
                review.last_error = str(e)
                try:
                    await db_session.commit()
                except Exception:
                    await db_session.rollback()
                    logger.exception(
                        "Failed to mark review as failed for PR %s", pr_id
                    )
        # Do NOT ack. XAUTOCLAIM will retry this pending message later.
        return

    # PHASE 3: Save result in a new DB session
    async with AsyncSessionLocal() as db_session:
        review = await db_session.get(Review, review_id)
        if not review:
            logger.error("Review %s disappeared before save, not acking", review_id)
            return

        review.status = ReviewStatus.COMPLETED
        REVIEWS_COMPLETED_TOTAL.labels(status="success").inc()
        REVIEW_DURATION_SECONDS.labels(status="success").observe(
            time.perf_counter() - review_started_at
        )
        review.summary = agent_result.summary
        review.risk_score = agent_result.risk_score
        review.agent_trace = getattr(
            agent_result,
            "tool_calls",
            getattr(agent_result, "trace", []),
        )
        review.last_error = None
        review.posted_to_github = getattr(agent_result, "posted_to_github", True)
        review.completed_at = datetime.now(timezone.utc)

        issues = getattr(agent_result, "issues", []) or []
        for issue in issues:
            sev_raw = (issue.get("severity") or "info").lower()
            try:
                sev = PRSeverity(sev_raw)
            except ValueError:
                sev = PRSeverity.INFO
            cat_raw = (issue.get("category") or "others").lower()
            try:
                cat = PRCategory(cat_raw)
            except ValueError:
                cat = PRCategory.OTHERS
            try:
                review_issue = ReviewIssue(
                    review_id=review.id,
                    category=cat,
                    severity=sev,
                    title=issue.get("title", "No title"),
                    description=issue.get("description", ""),
                    locations=issue.get("locations") or [],
                    source_file=issue.get("source_file") or issue.get("file"),
                    line_start=issue.get("line_start") or issue.get("line"),
                    line_end=issue.get("line_end"),
                    suggested_fix=issue.get("suggested_fix") or issue.get("suggestion"),
                    is_dismissed=False,
                    dismissal_reason=None,
                    dismissed_by_user_id=None,
                    dismissed_at=None,
                )
                review_issue.risk_score = calc_review_issue_risk_score(
                    category=review_issue.category,
                    severity=review_issue.severity,
                    has_locations=review_issue.locations is not None
                    and len(review_issue.locations) > 0,
                )
                db_session.add(review_issue)
            except Exception as e:
                logger.exception(
                    "Failed to create review issue for PR %s: %s", pr_id, e
                )
                continue

        try:
            await db_session.commit()
            logger.info("Saved review %s (PR: %s)", review.id, pr_number)
            # Only ack the message AFTER a successful DB save
            await redis_client.xack(STREAM_NAME, GROUP_NAME, message_id)
            logger.info("PR ID: %s acked", pr_id)
            await redis_client.publish(
                "devpulse:sse_events",
                json.dumps(
                    {
                        "user_id": str(owner_id),
                        "review_id": str(review.id),
                        "pr_number": pr_number,
                        "summary": review.summary,
                        "risk_score": review.risk_score,
                        "status": review.status.value
                        if hasattr(review.status, "value")
                        else str(review.status),
                        "completed_at": review.completed_at.isoformat()
                        if review.completed_at
                        else None,
                    }
                ),
            )
        except Exception:
            await db_session.rollback()
            logger.exception("Failed to save review for PR %s", pr_id)
            # Do not ack because DB save failed.
            return


async def run_worker_loop():
    """Run the review consume loop forever. Designed to run as an asyncio task
    launched from the FastAPI lifespan. The consumer group is already created
    by the API startup (create_consumer_group), so we do not create it here.
    """
    logger.info("In-process worker starting... (consumer: %s)", CONSUMER_NAME)
    redis_client = None
    try:
        redis_client = await init_redis_pool()
        logger.info("In-process worker Redis connection established")
        while True:
            try:
                await claim_and_process_pending(redis_client)
                messages = await redis_client.xreadgroup(
                    groupname=GROUP_NAME,
                    consumername=CONSUMER_NAME,
                    streams={STREAM_NAME: ">"},
                    count=1,
                    block=5000,
                )
            except RedisConnectionError as e:
                logger.error("Redis connection error: %s. Retrying in 5s...", e)
                await asyncio.sleep(5)
                continue

            if not messages:
                continue

            for stream_name, message_list in messages:
                for message_id, payload in message_list:
                    await process_review_message(
                        redis_client=redis_client,
                        message_id=message_id,
                        payload=payload,
                        is_retry=False,
                    )
    except asyncio.CancelledError:
        logger.info("In-process worker loop cancelled.")
    finally:
        if redis_client:
            await redis_client.aclose()
            logger.info("In-process worker Redis connection closed")
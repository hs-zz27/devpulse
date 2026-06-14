import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone

# Add the backend directory to sys.path so we can import 'app' as a top-level module
sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
)

from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.agent.loop import run_agent, calc_review_issue_risk_score
from app.api.producer import init_redis_pool

# Database / ORM imports
from app.core.database import AsyncSessionLocal
from app.models.enums import PRCategory, PRSeverity, ReviewStatus
from app.models.repo import PullRequest, Repository, Review, ReviewIssue
from app.models.user import User

logger = logging.getLogger(__name__)

CONSUMER_NAME = f"worker-{os.getpid()}"
STREAM_NAME = "devpulse:pr_review_queue"
GROUP_NAME = "devpulse_workers"

MAX_REVIEW_ATTEMPTS = 3
RETRY_IDLE_MS = 10 * 60 * 1000


async def main():
    """Worker main loop"""
    logger.info("🔧 DevPulse Worker starting... (consumer: %s)", CONSUMER_NAME)
    redis_client = None

    # ── STARTUP ──
    try:
        redis_client = await init_redis_pool()
        logger.info("✅ Redis connection established")

        # ── WORKER LOOP ──
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
                # Don't crash on Redis blip — log and retry after a delay
                logger.error("Redis connection error: %s. Retrying in 5s...", e)
                await asyncio.sleep(5)
                continue

            # timeout
            if not messages:
                continue

            for stream_name, message_list in messages:
                for message_id, payload in message_list:
                    pr_id = payload.get("pr_id")
                    if not pr_id:
                        logger.error(
                            "Malformed message (missing pr_id), acking and skipping. Payload: %s",
                            payload,
                        )
                        await redis_client.xack(STREAM_NAME, GROUP_NAME, message_id)
                        continue

                    logger.info("Received PR ID: %s", pr_id)

                    # Load PR + Repository + OAuth token from the DB
                    async with AsyncSessionLocal() as db_session:
                        # eager loading
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
                                "PR with id %s not found in database, acking and skipping",
                                pr_id,
                            )
                            await redis_client.xack(
                                STREAM_NAME,
                                GROUP_NAME,
                                message_id,
                            )
                            continue

                        repo = pr.repository
                        oauth = repo.owner.oauth_token if repo and repo.owner else None

                        if not oauth or not oauth.access_token:
                            logger.error(
                                "No OAuth token available for repo owner (repo=%s), acking and skipping",
                                repo.full_name if repo else "unknown",
                            )
                            await redis_client.xack(
                                STREAM_NAME,
                                GROUP_NAME,
                                message_id,
                            )
                            continue

                        # Add review to DB if not exists
                        review = Review(
                            pr_id=pr.id,
                            status=ReviewStatus.IN_PROGRESS,
                            commit_sha=pr.commit_sha,
                        )
                        db_session.add(review)
                        try:
                            await db_session.commit()
                            await db_session.refresh(review)
                        except IntegrityError:
                            await db_session.rollback()
                            logger.info(
                                "Review already exists for PR %s commit %s",
                                pr.id,
                                pr.commit_sha,
                            )
                            await redis_client.xack(
                                STREAM_NAME,
                                GROUP_NAME,
                                message_id,
                            )
                            continue

                        pr_data = {
                            "repo_full_name": repo.full_name,
                            "pr_number": pr.number,
                            "pr_id": str(pr.id),
                            "commit_sha": pr.commit_sha,
                        }

                        try:
                            agent_result = await run_agent(
                                github_token=oauth.access_token,
                                pr_data=pr_data,
                            )
                        except Exception as e:
                            logger.exception("Agent failed for PR %s: %s", pr_id, e)
                            # Do not ack so the message can be retried or inspected
                            review.attempt_count += 1
                            db_session.add(review)
                            try:
                                await db_session.commit()
                            except Exception:
                                await db_session.rollback()
                                logger.exception(
                                    "Failed to update attempt count for PR %s", pr_id
                                )
                                continue

                            if review.attempt_count >= MAX_ATTEMPTS:
                                logger.error(
                                    "Agent failed for PR %s after %d attempts, giving up",
                                    pr_id,
                                    MAX_ATTEMPTS,
                                )
                                review.status = ReviewStatus.FAILED
                                try:
                                    await db_session.commit()
                                except Exception:
                                    await db_session.rollback()
                                    logger.exception(
                                        "Failed to mark review as failed for PR %s",
                                        pr_id,
                                    )
                                    continue
                                await redis_client.xack(
                                    STREAM_NAME,
                                    GROUP_NAME,
                                    message_id,
                                )
                                continue
                            continue

                        # Persist review and any issues returned by the agent
                        review.status = ReviewStatus.COMPLETED
                        review.summary = agent_result.summary
                        review.risk_score = agent_result.risk_score
                        # Try to get agent_trace from AgentResult (it has tool_calls)
                        review.agent_trace = getattr(
                            agent_result,
                            "tool_calls",
                            getattr(agent_result, "trace", []),
                        )
                        # AgentResult doesn't natively have posted_to_github, assume True if succeeded
                        review.posted_to_github = getattr(
                            agent_result, "posted_to_github", True
                        )
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
                                    source_file=issue.get("source_file")
                                    or issue.get("file"),
                                    line_start=issue.get("line_start")
                                    or issue.get("line"),
                                    line_end=issue.get("line_end"),
                                    suggested_fix=issue.get("suggested_fix")
                                    or issue.get("suggestion"),
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
                                    "Failed to create review issue for PR %s: %s",
                                    pr_id,
                                    e,
                                )
                                continue

                        try:
                            await db_session.commit()
                            logger.info(
                                "Saved review %s (PR: %s)", review.id, pr.number
                            )

                            # Only ack the message AFTER a successful DB save
                            await redis_client.xack(
                                STREAM_NAME,
                                GROUP_NAME,
                                message_id,
                            )
                            logger.info("PR ID: %s acked", pr_id)

                            # publish to the asyncio.Queue
                            await redis_client.publish(
                                "devpulse:sse_events",
                                json.dumps(
                                    {
                                        "user_id": str(repo.owner_id),
                                        "review_id": str(review.id),
                                        "pr_number": pr.number,
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

    except asyncio.CancelledError:
        logger.info("Worker loop cancelled.")
    finally:
        # ── SHUTDOWN ──
        logger.info("🛑 DevPulse Worker shutting down...")
        if redis_client:
            await redis_client.aclose()
            logger.info("✅ Redis connection closed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())

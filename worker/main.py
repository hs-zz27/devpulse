"""
Worker entry point — runs as a SEPARATE PROCESS from the API.

This process:
1. Connects to Redis Streams
2. Loops forever pulling tasks
3. Runs the AI agent for each task
4. Writes results to PostgreSQL

TODO (Phase 2, Step 2.3): Implement following BUILD_GUIDE.md
"""

import asyncio
import logging
import sys
import os

# Add the backend directory to sys.path so we can import 'app' as a top-level module
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from backend.app.agent.loop import run_agent
from backend.app.api.producer import init_redis_pool
from redis.exceptions import ConnectionError as RedisConnectionError

# Database / ORM imports
from backend.app.core.database import AsyncSessionLocal
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from backend.app.models.repo import PullRequest, Repository, Review, ReviewIssue
from backend.app.models.user import User
from backend.app.models.enums import ReviewStatus, PRSeverity, PRCategory
from datetime import datetime, timezone


logger = logging.getLogger(__name__)

CONSUMER_NAME = f"worker-{os.getpid()}"
STREAM_NAME = "devpulse:pr_review_queue"
GROUP_NAME = "devpulse_workers"


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

            #timeout
            if not messages:
                continue

            for stream_name, message_list in messages:
                for message_id, payload in message_list:

                    pr_id = payload.get("pr_id")
                    if not pr_id:
                        logger.error(
                            "Malformed message (missing pr_id), acking and skipping. Payload: %s",
                            payload
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
                            logger.error("PR with id %s not found in database, acking and skipping", pr_id)
                            await redis_client.xack(STREAM_NAME, GROUP_NAME, message_id)
                            continue

                        repo = pr.repository
                        oauth = repo.owner.oauth_token if repo and repo.owner else None

                        if not oauth or not oauth.access_token:
                            logger.error("No OAuth token available for repo owner (repo=%s), acking and skipping", repo.full_name if repo else "unknown")
                            await redis_client.xack(STREAM_NAME, GROUP_NAME, message_id)
                            continue

                        pr_data = {"repo_full_name": repo.full_name, "pr_number": pr.number, "pr_id": str(pr.id)}

                    try:
                        agent_result = await run_agent(github_token=oauth.access_token, pr_data=pr_data)
                    except Exception as e:
                        logger.exception("Agent failed for PR %s: %s", pr_id, e)
                        # Do not ack so the message can be retried or inspected
                        continue
                    
                    # Persist review and any issues returned by the agent
                    async with AsyncSessionLocal() as write_session:
                        review = Review(
                            pr_id=pr.id,
                            status=ReviewStatus.COMPLETED,
                            risk_score=agent_result.risk_score,
                            summary=agent_result.summary,
                            posted_to_github=True,
                            agent_trace=agent_result.tool_calls,
                            completed_at=datetime.now(timezone.utc),
                        )
                        write_session.add(review)

                        issues = getattr(agent_result, "issues", []) or []
                        for issue in issues:
                            sev_raw = (issue.get("severity") or "info").lower()
                            try:
                                sev = PRSeverity(sev_raw)
                            except Exception:
                                sev = PRSeverity.INFO

                            cat_raw = (issue.get("category") or "others").lower()
                            try:
                                cat = PRCategory(cat_raw)
                            except Exception:
                                cat = PRCategory.OTHERS

                            review_issue = ReviewIssue(
                                severity=sev,
                                category=cat,
                                file_path=issue.get("file"),
                                line_number=issue.get("line"),
                                description=issue.get("description", ""),
                                suggestion=issue.get("suggestion", ""),
                            )
                            review.review_issues.append(review_issue)

                        try:
                            await write_session.commit()
                            logger.info("Saved review %s (PR: %s)", review.id, pr.number)
                            
                            # Only ack the message AFTER a successful DB save
                            await redis_client.xack(STREAM_NAME, GROUP_NAME, message_id)
                            logger.info("PR ID: %s acked", pr_id)
                            
                        except Exception:
                            await write_session.rollback()
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

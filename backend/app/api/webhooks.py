import json
import logging
from datetime import datetime

from fastapi import APIRouter, Request, Header, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db
from app.core.security import verify_webhook_signature
from app.models.repo import Repository, PullRequest
from app.models.enums import PRState
from app.api.producer import enqueue_pr_review

logger = logging.getLogger(__name__)

router = APIRouter()

_RELEVANT_PR_ACTIONS = {"opened", "closed", "reopened", "synchronize"}


def _parse_pr_state(pr_data: dict) -> PRState:
    state_str = pr_data.get("state", "open")
    merged = pr_data.get("merged", False)

    if state_str == "open":
        return PRState.OPEN
    if merged:
        return PRState.MERGED
    return PRState.CLOSED


@router.post("/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256"),
    x_github_event: str = Header(None, alias="X-GitHub-Event"),
    db: AsyncSession = Depends(get_db),
):
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    repo_data = payload.get("repository")
    if not repo_data:
        return {"status": "ignored", "reason": "No repository in payload"}

    github_repo_id = repo_data.get("id")
    result = await db.execute(
        select(Repository).where(Repository.github_repo_id == github_repo_id)
    )
    repo = result.scalars().first()

    # Return 401 for ALL auth failures, we never reveal whether the repo exists heh :)
    if not repo or not repo.webhook_secret or not x_hub_signature_256:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not verify_webhook_signature(raw_body, x_hub_signature_256, repo.webhook_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")

    if x_github_event == "pull_request":
        action = payload.get("action")

        if action not in _RELEVANT_PR_ACTIONS:
            logger.debug("Ignoring PR action=%s for repo %s", action, github_repo_id)
            return {"status": "ignored", "reason": f"PR action '{action}' not tracked"}

        pr_data = payload.get("pull_request", {})
        github_pr_id = pr_data.get("id")
        number = pr_data.get("number")
        title = pr_data.get("title")
        author_login = pr_data.get("user", {}).get("login")
        pr_state = _parse_pr_state(pr_data)

        merged_at_str = pr_data.get("merged_at")
        merged_at: datetime | None = None
        if merged_at_str:
            try:
                merged_at = datetime.fromisoformat(
                    merged_at_str.replace("Z", "+00:00")
                )
            except ValueError:
                logger.warning("Could not parse merged_at=%r", merged_at_str)

        
        pr_result = await db.execute(
            select(PullRequest).where(PullRequest.github_pr_id == github_pr_id)
        )
        pr = pr_result.scalars().first()

        if not pr:
            pr = PullRequest(
                repo_id=repo.id,
                github_pr_id=github_pr_id,
                number=number,
                title=title,
                author_login=author_login,
                state=pr_state,
                merged_at=merged_at,
            )
            db.add(pr)
            logger.info("Created PR #%s (github_pr_id=%s)", number, github_pr_id)
        else:
            pr.title = title
            pr.state = pr_state
            pr.merged_at = merged_at
            logger.info(
                "Updated PR #%s → state=%s merged_at=%s",
                number, pr_state, merged_at,
            )

        await db.commit()
        if action in ("opened", "synchronize"):
            logger.info("Adding PR #%s to review queue", number)
            await enqueue_pr_review(pr.id)
        
        return {
            "status": "success",
            "message": f"Processed PR #{number} action: {action}",
        }
    #ignore other type events
    return {"status": "ignored", "event": x_github_event}

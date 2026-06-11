from datetime import datetime, timedelta, timezone
import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.repo import PullRequest, Deployment
from app.models.enums import DeploymentEnvironment, DeploymentStatus

router = APIRouter()

@router.get("/dora/{repo_id}")
async def get_dora_metrics(
    repo_id: uuid.UUID,
    days: int = 30,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns all 4 DORA metrics for a repo over the last N days.
    """
    # # Validate days
    # days = max(days, 1)
    # since = datetime.now(timezone.utc) - timedelta(days=days)

    # # 1. Deployment Frequency
    # stmt_freq = select(func.count(Deployment.id)).where(
    #     Deployment.repo_id == repo_id,
    #     Deployment.environment == DeploymentEnvironment.PRODUCTION,
    #     Deployment.status == DeploymentStatus.SUCCESS,
    #     Deployment.deployed_at >= since,
    # )
    # total_deploys = (await db.execute(stmt_freq)).scalar() or 0
    # freq_per_day = total_deploys / days

    # # 2. Change Failure Rate
    # stmt_failed = select(func.count(Deployment.id)).where(
    #     Deployment.repo_id == repo_id,
    #     Deployment.environment == DeploymentEnvironment.PRODUCTION,
    #     Deployment.status == DeploymentStatus.FAILED,
    #     Deployment.deployed_at >= since,
    # )
    # failed_deploys = (await db.execute(stmt_failed)).scalar() or 0

    # stmt_total_all = select(func.count(Deployment.id)).where(
    #     Deployment.repo_id == repo_id,
    #     Deployment.environment == DeploymentEnvironment.PRODUCTION,
    #     Deployment.deployed_at >= since,
    # )
    # total_all = (await db.execute(stmt_total_all)).scalar() or 0

    # failure_rate = (failed_deploys / total_all * 100) if total_all > 0 else 0.0

    # # 3. Lead Time for Changes
    # # Approximation: PR opened_at -> first successful production deploy
    # first_deploys_subq = (
    #     select(
    #         Deployment.pr_id,
    #         func.min(Deployment.deployed_at).label("first_deploy_time"),
    #     )
    #     .where(
    #         Deployment.repo_id == repo_id,
    #         Deployment.environment == DeploymentEnvironment.PRODUCTION,
    #         Deployment.status == DeploymentStatus.SUCCESS,
    #         Deployment.deployed_at >= since,
    #         Deployment.pr_id.isnot(None),
    #     )
    #     .group_by(Deployment.pr_id)
    #     .subquery()
    # )

    # stmt_lead = (
    #     select(
    #         func.avg(
    #             func.extract(
    #                 "epoch",
    #                 first_deploys_subq.c.first_deploy_time - PullRequest.opened_at,
    #             )
    #         )
    #     )
    #     .select_from(PullRequest)
    #     .join(first_deploys_subq, PullRequest.id == first_deploys_subq.c.pr_id)
    #     .where(PullRequest.repo_id == repo_id)
    # )

    # avg_lead_seconds = (await db.execute(stmt_lead)).scalar()
    # lead_time_hours = (avg_lead_seconds / 3600) if avg_lead_seconds else 0.0

    # # 4. MTTR
    # stmt_deploys = (
    #     select(Deployment.status, Deployment.deployed_at)
    #     .where(
    #         Deployment.repo_id == repo_id,
    #         Deployment.environment == DeploymentEnvironment.PRODUCTION,
    #         Deployment.deployed_at >= since,
    #     )
    #     .order_by(Deployment.deployed_at.asc())
    # )

    # deploy_rows = (await db.execute(stmt_deploys)).all()

    # restore_durations: list[float] = []
    # failure_started_at: datetime | None = None

    # for status, deployed_at in deploy_rows:
    #     if status == DeploymentStatus.FAILED and failure_started_at is None:
    #         failure_started_at = deployed_at
    #     elif status == DeploymentStatus.SUCCESS and failure_started_at is not None:
    #         delta_seconds = (deployed_at - failure_started_at).total_seconds()
    #         restore_durations.append(delta_seconds)
    #         failure_started_at = None

    # mttr_hours = (
    #     sum(restore_durations) / len(restore_durations) / 3600
    #     if restore_durations
    #     else 0.0
    # )

    # ── DORA performance classification helpers ──────────────────────────────
    # def classify_freq(v: float) -> str:
    #     if v >= 1: return "elite"
    #     if v >= 1/7: return "high"
    #     if v >= 1/30: return "medium"
    #     return "low"

    # def classify_lead(hours: float) -> str:
    #     if hours < 1: return "elite"
    #     if hours <= 24: return "high"
    #     if hours <= 24 * 7: return "medium"
    #     return "low"

    # def classify_cfr(pct: float) -> str:
    #     if pct <= 5: return "elite"
    #     if pct <= 10: return "high"
    #     if pct <= 15: return "medium"
    #     return "low"

    # def classify_mttr(hours: float) -> str:
    #     if hours < 1: return "elite"
    #     if hours <= 24: return "high"
    #     if hours <= 24 * 7: return "medium"
    #     return "low"

    # DUMMY DATA FOR FRONTEND DEVELOPMENT
    return {
        "repo_id": str(repo_id),
        "period_days": days,
        "deployment_frequency": {
            "value": 1.5,               # deployments per day
            "label": "Per day",
            "performance": "high",      # elite/high/medium/low
        },
        "lead_time_for_changes": {
            "value": 24.5,              # hours
            "label": "Hours",
            "performance": "medium",
        },
        "change_failure_rate": {
            "value": 4.2,               # percentage 0-100
            "label": "%",
            "performance": "elite",
        },
        "mean_time_to_restore": {
            "value": 2.1,               # hours
            "label": "Hours",
            "performance": "high",
        },
    }
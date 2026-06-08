from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.models.user import User

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum as SAEnum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import (
    PRCategory,
    PRSeverity,
    PRState,
    ReviewStatus,
    DeploymentEnvironment,
    DeploymentStatus,
)


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    github_repo_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        unique=True,
        index=True,
    )

    full_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    webhook_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    webhook_secret: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    owner: Mapped["User"] = relationship(back_populates="repositories")
    pull_requests: Mapped[list["PullRequest"]] = relationship(
        back_populates="repository",
        cascade="all, delete-orphan",
    )
    deployments: Mapped[list["Deployment"]] = relationship(
        back_populates="repository",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Repository {self.full_name}>"


class PullRequest(Base):
    __tablename__ = "pull_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    repo_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    github_pr_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        unique=True,
        index=True,
    )

    number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    author_login: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    state: Mapped[PRState] = mapped_column(
        SAEnum(PRState, name="pr_state"),
        nullable=False,
    )

    lines_added: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    lines_removed: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    files_changed: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    has_migrations: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    merged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    repository: Mapped["Repository"] = relationship(back_populates="pull_requests")
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="pull_request",
        cascade="all, delete-orphan",
    )
    deployments: Mapped[list["Deployment"]] = relationship(
        back_populates="pull_request",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<PullRequest #{self.number}>"


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    pr_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[ReviewStatus] = mapped_column(
        SAEnum(ReviewStatus, name="review_status"),
        nullable=False,
        default=ReviewStatus.PENDING,
    )

    risk_score: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    posted_to_github: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    agent_trace: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    pull_request: Mapped["PullRequest"] = relationship(back_populates="reviews")
    review_issues: Mapped[list["ReviewIssue"]] = relationship(
        back_populates="review",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Review risk_score={self.risk_score}>"


class ReviewIssue(Base):
    __tablename__ = "review_issues"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    review_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    severity: Mapped[PRSeverity] = mapped_column(
        SAEnum(PRSeverity, name="pr_severity"),
        nullable=False,
    )

    category: Mapped[PRCategory] = mapped_column(
        SAEnum(PRCategory, name="pr_category"),
        nullable=False,
    )

    file_path: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    line_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    suggestion: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    review: Mapped["Review"] = relationship(back_populates="review_issues")

    def __repr__(self) -> str:
        return f"<ReviewIssue {self.severity}>"


class Deployment(Base):
    __tablename__ = "deployments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    repo_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    pr_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    environment: Mapped[DeploymentEnvironment] = mapped_column(
        SAEnum(DeploymentEnvironment, name="deployment_environment"),
        nullable=False,
    )

    status: Mapped[DeploymentStatus] = mapped_column(
        SAEnum(DeploymentStatus, name="deployment_status"),
        nullable=False,
    )

    deployed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    deploy_duration: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    repository: Mapped["Repository"] = relationship(back_populates="deployments")
    pull_request: Mapped["PullRequest | None"] = relationship(back_populates="deployments")

    def __repr__(self) -> str:
        return f"<Deployment {self.environment} status={self.status}>"
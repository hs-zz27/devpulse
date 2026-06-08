"""
Database setup — SQLAlchemy async engine + session factory.

Key concepts:
- async_engine: the connection to PostgreSQL (uses asyncpg driver)
- AsyncSession: like a unit of work — you open one per request, do your queries, close it
- Base: the parent class for all your ORM models (like @Entity in JPA)
"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


# ── Engine ────────────────────────────────────────────────────────────────────
# The engine manages the connection pool to PostgreSQL.
# pool_size=10 means up to 10 simultaneous DB connections.
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    echo=settings.ENVIRONMENT == "development",  # Logs SQL in dev mode
)

# ── Session Factory ───────────────────────────────────────────────────────────
# A "factory" that creates new session objects when called.
# expire_on_commit=False: keeps objects accessible after committing
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ── Base Model ────────────────────────────────────────────────────────────────
# All your ORM models (user.py, repo.py, etc.) will inherit from this.
class Base(DeclarativeBase):
    pass


# ── Dependency: get_db ────────────────────────────────────────────────────────
# FastAPI "dependencies" are functions that run before your endpoint.
# This one opens a DB session, gives it to the endpoint, then closes it.
# Usage in an endpoint:
#   async def my_endpoint(db: AsyncSession = Depends(get_db)):
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Init DB ───────────────────────────────────────────────────────────────────
# Called once on startup (in main.py lifespan).
# In production you'll use Alembic migrations instead.
async def init_db():
    async with engine.begin() as conn:
        # Just verifies the connection works
        await conn.run_sync(lambda sync_conn: None)

"""
DevPulse Backend — FastAPI Application Entry Point

This is where the app is created and all routers are registered.
Think of this like Spring Boot's main class + @ComponentScan combined.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from app.core.database import init_db
from app.api import webhooks, auth, users, repos, reviews , metrics , chat
from app.api.producer import create_consumer_group
from app.api.reviews import listen_to_redis_pubsub
from app.api.metrics import QUEUE_DEPTH
from app.api.producer import init_redis_pool
logger = logging.getLogger(__name__)




async def _refresh_queue_depth(redis_client, interval: int = 5):
    while True:
        try:
            depth = await redis_client.xlen("devpulse:pr_review_queue")
            QUEUE_DEPTH.set(depth)
        except Exception:
            logger.exception("Failed to refresh queue depth gauge")
        await asyncio.sleep(interval)



# ── Lifespan (startup + shutdown logic) ─────────────────────────────────────
# This runs ONCE when the server starts and ONCE when it stops.
# Use it for: DB connection pool, Redis connection, loading configs, etc.
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── STARTUP ──
    print("🚀 DevPulse API starting up...")
    await init_db()
    print("✅ Database connected")
    await create_consumer_group()
    print("✅ Consumer group created in Redis")
    redis_task = asyncio.create_task(listen_to_redis_pubsub())
    print("📡 Started Redis Pub/Sub listener for SSE events")
    redis_client = await init_redis_pool()
    queue_depth_task = asyncio.create_task(_refresh_queue_depth(redis_client))   # ⬅️ START IT

    yield

    # ── SHUTDOWN ──
    print("🛑 DevPulse API shutting down...")
    redis_task.cancel()
    try:
        await redis_task
    except asyncio.CancelledError:
        pass


# ── Create the FastAPI app ───────────────────────────────────────────────────
app = FastAPI(
    title="DevPulse API",
    description="Engineering Intelligence Platform — AI-powered PR reviews + DORA metrics",
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS Middleware ──────────────────────────────────────────────────────────
# Allows your React frontend (port 3000) to call this API (port 8000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],  # Add your Railway URL here in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health Check ─────────────────────────────────────────────────────────────
# Always build this first. If this works, the server is alive.
@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "devpulse-api"}

# ── Prometheus Metrics Endpoint ──────────────────────────────────────────────
@app.get("/metrics", tags=["metrics"])
async def get_prometheus_metrics():
    """
    Exposes Prometheus metrics. Scraped by Prometheus server.
    """
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)



# ── TODO: Register routers here as you build them ───────────────────────────
# from app.api import webhooks, metrics, reviews, chat

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(users.router, tags=["users"])
app.include_router(repos.router, prefix="/repos", tags=["repos"])

app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
app.include_router(metrics.router, prefix="/metrics", tags=["metrics"])
app.include_router(reviews.router, prefix="/reviews", tags=["reviews"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])

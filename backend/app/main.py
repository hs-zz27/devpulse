"""DevPulse Backend — FastAPI Application Entry Point

This is where the app is created and all routers are registered.
Think of this like Spring Boot's main class + @ComponentScan combined.
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app.core.database import init_db
from app.api import webhooks, auth, users, repos, reviews, metrics, chat
from app.api.producer import create_consumer_group
from app.api.reviews import listen_to_redis_pubsub
from app.api.metrics import QUEUE_DEPTH
from app.api.producer import init_redis_pool
from app.worker_runner import run_worker_loop

logger = logging.getLogger(__name__)


async def _refresh_queue_depth(redis_client, interval: int = 5):
    while True:
        try:
            depth = await redis_client.xlen("devpulse:pr_review_queue")
            QUEUE_DEPTH.set(depth)
        except Exception:
            logger.exception("Failed to refresh queue depth gauge")
        await asyncio.sleep(interval)


# Lifespan (startup + shutdown logic)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP
    print("DevPulse API starting up...")
    await init_db()
    print("Database connected")

    await create_consumer_group()
    print("Consumer group created in Redis")

    redis_task = asyncio.create_task(listen_to_redis_pubsub())
    print("Started Redis Pub/Sub listener for SSE events")

    redis_client = await init_redis_pool()
    queue_depth_task = asyncio.create_task(_refresh_queue_depth(redis_client))
    print("Started queue-depth gauge refresher")

    # In-process review worker (free Render deploy).
    # Render's free tier has no separate Background Worker, so when
    # RUN_WORKER_IN_PROCESS=true we drain the Redis review queue inside this
    # same process. Metrics live here, so GET /metrics already exposes the
    # worker's review counters and histograms.
    worker_task = None
    if os.getenv("RUN_WORKER_IN_PROCESS", "false").lower() == "true":
        worker_task = asyncio.create_task(run_worker_loop())
        print("Started in-process review worker")

    yield

    # SHUTDOWN
    print("DevPulse API shutting down...")
    tasks = [redis_task, queue_depth_task]
    if worker_task is not None:
        tasks.append(worker_task)

    for task in tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    await redis_client.aclose()
    print("Redis queue-depth connection closed")


# Create the FastAPI app
app = FastAPI(
    title="DevPulse API",
    description="Engineering Intelligence Platform — AI-powered PR reviews + DORA metrics",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://devpulse-three-mu.vercel.app",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health Check
@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "devpulse-api"}


# Prometheus Metrics Endpoint
@app.get("/metrics", tags=["metrics"])
async def get_prometheus_metrics():
    """
    Exposes Prometheus metrics. Scraped by Prometheus server.
    """
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(users.router, tags=["users"])
app.include_router(repos.router, prefix="/repos", tags=["repos"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
app.include_router(metrics.router, prefix="/metrics", tags=["metrics"])
app.include_router(reviews.router, prefix="/reviews", tags=["reviews"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
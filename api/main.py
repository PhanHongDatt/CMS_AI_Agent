"""FastAPI application — serves REST API + Telegram webhook endpoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes import alerts, approvals, autonomy, health, incidents, pipeline, webhook
from core.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(log_level="INFO", log_format="json")
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agentic DevOps Platform",
        description="AI-driven incident management with safe autonomous remediation",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(health.router)
    app.include_router(alerts.router)
    app.include_router(incidents.router)
    app.include_router(approvals.router)
    app.include_router(autonomy.router)
    app.include_router(pipeline.router)
    app.include_router(webhook.router)

    return app


app = create_app()

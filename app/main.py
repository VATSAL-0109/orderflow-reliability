from contextlib import asynccontextmanager
import logging
from collections.abc import AsyncGenerator

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.config import get_settings
from app.logging_config import setup_logging
from app.schemas import HealthResponse

settings = get_settings()
logger = logging.getLogger("orderflow.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context for startup and shutdown events."""
    setup_logging(settings.LOG_LEVEL)
    logger.info(
        "Application starting up",
        extra={"environment": settings.ENVIRONMENT, "debug": settings.DEBUG},
    )
    yield
    logger.info("Application shutting down")


app = FastAPI(
    title=settings.APP_NAME,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Liveness probe endpoint."""
    return HealthResponse(status="healthy", service=settings.APP_NAME)


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus metrics scrape endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

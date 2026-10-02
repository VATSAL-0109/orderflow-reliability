from contextlib import asynccontextmanager
import logging
import time
import uuid
from collections.abc import AsyncGenerator

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.config import get_settings
from app.database import engine, update_db_pool_metrics
from app.logging_config import request_id_ctx, setup_logging
from app.metrics import (
    HTTP_ERRORS_TOTAL,
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
)
from app.models import Base
from app.routes.orders import router as orders_router
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

    # Initialize database tables
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialized successfully")
    except Exception as exc:
        logger.error(
            "Failed to initialize database tables", extra={"error": str(exc)}
        )
        raise

    yield

    logger.info("Application shutting down")
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    """Middleware for request-id tracing, structured logging, and HTTP metrics."""
    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    token = request_id_ctx.set(req_id)

    # Normalize endpoint name to prevent Prometheus cardinality explosion
    path = request.url.path
    if path.startswith("/orders/") and path != "/orders/":
        endpoint = "/orders/{order_id}"
    else:
        endpoint = path

    start_time = time.perf_counter()
    try:
        response = await call_next(request)
        duration = time.perf_counter() - start_time

        # Track Prometheus HTTP metrics
        status_code = str(response.status_code)
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method, endpoint=endpoint, status=status_code
        ).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(
            method=request.method, endpoint=endpoint
        ).observe(duration)

        if response.status_code >= 400:
            HTTP_ERRORS_TOTAL.labels(
                method=request.method, endpoint=endpoint, status_code=status_code
            ).inc()

        logger.info(
            "HTTP request completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration * 1000, 2),
            },
        )

        response.headers["X-Request-ID"] = req_id
        return response

    except Exception as exc:
        duration = time.perf_counter() - start_time
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method, endpoint=endpoint, status="500"
        ).inc()
        HTTP_ERRORS_TOTAL.labels(
            method=request.method, endpoint=endpoint, status_code="500"
        ).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(
            method=request.method, endpoint=endpoint
        ).observe(duration)

        logger.error(
            "Unhandled request exception",
            extra={
                "method": request.method,
                "path": request.url.path,
                "error": str(exc),
                "duration_ms": round(duration * 1000, 2),
            },
            exc_info=True,
        )
        raise exc
    finally:
        request_id_ctx.reset(token)


app.include_router(orders_router)


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Liveness probe endpoint."""
    return HealthResponse(status="healthy", service=settings.APP_NAME)


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus metrics scrape endpoint."""
    update_db_pool_metrics()
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

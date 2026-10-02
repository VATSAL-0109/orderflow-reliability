from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import logging
import time
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.metrics import (
    DB_CONNECTION_WAIT_SECONDS,
    DB_POOL_AVAILABLE_CONNECTIONS,
    DB_POOL_CHECKED_OUT_CONNECTIONS,
    DB_POOL_OVERFLOW_CONNECTIONS,
    DB_POOL_TIMEOUTS_TOTAL,
)

settings = get_settings()
logger = logging.getLogger("orderflow.database")

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


def update_db_pool_metrics() -> None:
    """Read actual SQLAlchemy pool state and update Prometheus gauges."""
    try:
        pool = engine.sync_engine.pool
        DB_POOL_CHECKED_OUT_CONNECTIONS.set(pool.checkedout())
        DB_POOL_AVAILABLE_CONNECTIONS.set(pool.checkedin())
        DB_POOL_OVERFLOW_CONNECTIONS.set(max(0, pool.overflow()))
    except Exception as exc:
        logger.warning("Failed to collect pool metrics", extra={"error": str(exc)})


@asynccontextmanager
async def acquire_db_connection() -> AsyncGenerator[tuple[AsyncConnection, float], None]:
    """Acquire a physical DB connection from the engine's connection pool.

    Measures the exact duration spent waiting for the connection pool.
    Increments DB_POOL_TIMEOUTS_TOTAL if the acquisition times out.
    Yields (connection, wait_duration_seconds).
    """
    t_wait_start = time.perf_counter()
    try:
        async with engine.connect() as conn:
            wait_seconds = time.perf_counter() - t_wait_start
            DB_CONNECTION_WAIT_SECONDS.observe(wait_seconds)
            update_db_pool_metrics()
            yield conn, wait_seconds
    except SQLAlchemyTimeoutError as exc:
        DB_POOL_TIMEOUTS_TOTAL.inc()
        update_db_pool_metrics()
        logger.error(
            "Database connection pool checkout timeout",
            extra={"pool_timeout_seconds": settings.DB_POOL_TIMEOUT},
        )
        raise exc
    finally:
        update_db_pool_metrics()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency yielding an asynchronous database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

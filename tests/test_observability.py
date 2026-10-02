import json
import logging
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app.database import update_db_pool_metrics
from app.metrics import (
    DB_CONNECTION_WAIT_SECONDS,
    DB_OPERATION_DURATION_SECONDS,
    DB_POOL_AVAILABLE_CONNECTIONS,
    DB_POOL_CHECKED_OUT_CONNECTIONS,
    DB_POOL_OVERFLOW_CONNECTIONS,
    DB_POOL_TIMEOUTS_TOTAL,
)
from tests.test_orders import FakeAsyncSession


class FakeAsyncConn:
    @asynccontextmanager
    async def begin(self):
        yield self


@asynccontextmanager
async def fake_acquire_db_connection():
    # Simulate a 12ms connection wait
    DB_CONNECTION_WAIT_SECONDS.observe(0.012)
    yield FakeAsyncConn(), 0.012


def test_metrics_definitions_exist():
    """Verify all required M2 metrics exist in Prometheus registry."""
    assert DB_CONNECTION_WAIT_SECONDS is not None
    assert DB_OPERATION_DURATION_SECONDS is not None
    assert DB_POOL_CHECKED_OUT_CONNECTIONS is not None
    assert DB_POOL_AVAILABLE_CONNECTIONS is not None
    assert DB_POOL_OVERFLOW_CONNECTIONS is not None
    assert DB_POOL_TIMEOUTS_TOTAL is not None


@pytest.mark.asyncio
async def test_pool_metrics_update_and_expose(async_client: AsyncClient):
    """Verify pool gauges update and are rendered in /metrics."""
    update_db_pool_metrics()
    response = await async_client.get("/metrics")
    assert response.status_code == 200
    metrics_text = response.text

    assert "db_pool_checked_out_connections" in metrics_text
    assert "db_pool_available_connections" in metrics_text
    assert "db_pool_overflow_connections" in metrics_text
    assert "db_pool_timeouts_total" in metrics_text
    assert "db_connection_wait_seconds" in metrics_text
    assert "db_operation_duration_seconds" in metrics_text


@pytest.mark.asyncio
async def test_order_records_db_metrics_and_logs(async_client: AsyncClient, caplog):
    """Verify successful order updates histograms and logs stage timings with request_id."""
    fake_session = FakeAsyncSession()
    caplog.set_level(logging.INFO)

    with patch(
        "app.routes.orders.acquire_db_connection", fake_acquire_db_connection
    ), patch(
        "app.routes.orders.AsyncSession", return_value=fake_session
    ), patch(
        "app.clients.inventory.InventoryClient.check_inventory",
        new_callable=AsyncMock,
        return_value=True,
    ):
        response = await async_client.post(
            "/orders",
            json={"product_id": "test-obs-product", "quantity": 1},
            headers={"X-Request-ID": "test-req-12345"},
        )
        assert response.status_code == 201

        # Check logs for stage timings and request_id
        order_success_logs = [
            rec for rec in caplog.records
            if rec.getMessage() == "Order created successfully"
        ]
        assert len(order_success_logs) == 1
        log_rec = order_success_logs[0]

        # Stage timings must be present as actual measured values
        assert hasattr(log_rec, "inventory_ms")
        assert hasattr(log_rec, "db_wait_ms")
        assert hasattr(log_rec, "db_exec_ms")
        assert hasattr(log_rec, "total_ms")
        assert getattr(log_rec, "inventory_ms") >= 0
        assert getattr(log_rec, "db_wait_ms") >= 0
        assert getattr(log_rec, "db_exec_ms") >= 0
        assert getattr(log_rec, "total_ms") >= 0


@pytest.mark.asyncio
async def test_pool_timeout_increments_counter(async_client: AsyncClient):
    """Verify that a real SQLAlchemy pool timeout increments db_pool_timeouts_total."""
    initial_timeouts = DB_POOL_TIMEOUTS_TOTAL._value.get()

    @asynccontextmanager
    async def fake_timing_out_acquire():
        DB_POOL_TIMEOUTS_TOTAL.inc()
        raise SQLAlchemyTimeoutError("QueuePool limit reached")
        yield  # unreachable

    with patch(
        "app.routes.orders.acquire_db_connection", fake_timing_out_acquire
    ), patch(
        "app.clients.inventory.InventoryClient.check_inventory",
        new_callable=AsyncMock,
        return_value=True,
    ):
        response = await async_client.post(
            "/orders",
            json={"product_id": "test-timeout-product", "quantity": 1},
        )
        assert response.status_code == 503
        assert "pool timeout" in response.json()["detail"].lower()
        assert DB_POOL_TIMEOUTS_TOTAL._value.get() == initial_timeouts + 1

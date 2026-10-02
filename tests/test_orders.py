from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.clients.inventory import (
    InventoryDownstreamError,
    InventoryTimeoutError,
    InventoryUnavailableError,
)
from app.models import Order


class FakeAsyncSession:
    """Mock database session for isolated testing."""

    def __init__(self, execute_result=None):
        self.added = []
        self._execute_result = execute_result

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    def begin(self):
        return self

    def add(self, obj):
        obj.id = 42
        self.added.append(obj)

    async def flush(self):
        pass

    async def refresh(self, obj):
        if not getattr(obj, "id", None):
            obj.id = 42

    async def execute(self, stmt):
        from unittest.mock import MagicMock
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = self._execute_result
        return mock_result


class FakeAsyncConn:
    """Mock database connection that can begin a transaction."""

    @asynccontextmanager
    async def begin(self):
        yield self


@asynccontextmanager
async def fake_acquire_db_connection():
    yield FakeAsyncConn(), 0.005


@pytest.mark.asyncio
async def test_health_check(async_client: AsyncClient):
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "OrderFlow"


@pytest.mark.asyncio
async def test_metrics_endpoint(async_client: AsyncClient):
    response = await async_client.get("/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text


@pytest.mark.asyncio
async def test_create_order_success(async_client: AsyncClient):
    fake_session = FakeAsyncSession()
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
            json={"product_id": "laptop-001", "quantity": 2},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == 42
        assert data["product_id"] == "laptop-001"
        assert data["quantity"] == 2
        assert data["status"] == "CONFIRMED"
        assert "X-Request-ID" in response.headers


@pytest.mark.asyncio
async def test_create_order_inventory_unavailable(async_client: AsyncClient):
    with patch(
        "app.clients.inventory.InventoryClient.check_inventory",
        new_callable=AsyncMock,
        side_effect=InventoryUnavailableError("Product 'laptop-001' is unavailable in inventory"),
    ):
        response = await async_client.post(
            "/orders",
            json={"product_id": "laptop-001", "quantity": 1},
        )
        assert response.status_code == 409
        assert "unavailable" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_order_inventory_timeout(async_client: AsyncClient):
    with patch(
        "app.clients.inventory.InventoryClient.check_inventory",
        new_callable=AsyncMock,
        side_effect=InventoryTimeoutError("Inventory service timed out"),
    ):
        response = await async_client.post(
            "/orders",
            json={"product_id": "laptop-001", "quantity": 1},
        )
        assert response.status_code == 504
        assert "timed out" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_order_inventory_downstream_error(async_client: AsyncClient):
    with patch(
        "app.clients.inventory.InventoryClient.check_inventory",
        new_callable=AsyncMock,
        side_effect=InventoryDownstreamError(500, "Internal Server Error"),
    ):
        response = await async_client.post(
            "/orders",
            json={"product_id": "laptop-001", "quantity": 1},
        )
        assert response.status_code == 502
        assert "downstream inventory error" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_order_invalid_quantity(async_client: AsyncClient):
    # quantity <= 0
    response = await async_client.post(
        "/orders",
        json={"product_id": "laptop-001", "quantity": 0},
    )
    assert response.status_code == 422

    response_neg = await async_client.post(
        "/orders",
        json={"product_id": "laptop-001", "quantity": -5},
    )
    assert response_neg.status_code == 422


@pytest.mark.asyncio
async def test_create_order_empty_product_id(async_client: AsyncClient):
    response = await async_client.post(
        "/orders",
        json={"product_id": "   ", "quantity": 1},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_order_success(async_client: AsyncClient):
    existing_order = Order(id=10, product_id="keyboard-101", quantity=1, status="CONFIRMED")
    fake_session = FakeAsyncSession(execute_result=existing_order)
    with patch(
        "app.routes.orders.acquire_db_connection", fake_acquire_db_connection
    ), patch(
        "app.routes.orders.AsyncSession", return_value=fake_session
    ):
        response = await async_client.get("/orders/10")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 10
        assert data["product_id"] == "keyboard-101"
        assert data["quantity"] == 1
        assert data["status"] == "CONFIRMED"


@pytest.mark.asyncio
async def test_get_order_not_found(async_client: AsyncClient):
    fake_session = FakeAsyncSession(execute_result=None)
    with patch(
        "app.routes.orders.acquire_db_connection", fake_acquire_db_connection
    ), patch(
        "app.routes.orders.AsyncSession", return_value=fake_session
    ):
        response = await async_client.get("/orders/999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

import logging
import time
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.clients.inventory import (
    InventoryClient,
    InventoryDownstreamError,
    InventoryTimeoutError,
    InventoryUnavailableError,
)
from app.config import Settings, get_settings
from app.database import AsyncSessionLocal
from app.metrics import DB_QUERY_DURATION_SECONDS
from app.models import Order
from app.schemas import OrderCreate, OrderResponse

logger = logging.getLogger("orderflow.orders")
router = APIRouter(prefix="/orders", tags=["orders"])


def get_inventory_client(
    settings: Settings = Depends(get_settings),
) -> InventoryClient:
    """Dependency providing an configured InventoryClient."""
    return InventoryClient(
        base_url=settings.INVENTORY_SERVICE_URL,
        timeout_seconds=settings.INVENTORY_TIMEOUT_SECONDS,
    )


@router.post(
    "",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new order",
)
async def create_order(
    payload: OrderCreate,
    inventory_client: InventoryClient = Depends(get_inventory_client),
) -> OrderResponse:
    """Healthy Order creation flow:

    1. Check inventory availability via external HTTP call (NO DB connection open).
    2. After inventory succeeds, open DB session/transaction.
    3. Persist order and commit.
    4. Return created order.
    """
    logger.info(
        "Initiating order creation",
        extra={"product_id": payload.product_id, "quantity": payload.quantity},
    )

    # Step 1: Check downstream inventory FIRST (no DB connection held)
    try:
        await inventory_client.check_inventory(payload.product_id)
    except InventoryUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except InventoryTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Downstream inventory service timed out",
        ) from exc
    except InventoryDownstreamError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Downstream inventory error: {str(exc)}",
        ) from exc

    # Step 2: Acquire DB session only AFTER downstream check succeeds
    t0 = time.perf_counter()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            order = Order(
                product_id=payload.product_id,
                quantity=payload.quantity,
                status="CONFIRMED",
            )
            session.add(order)
            await session.flush()
            order_data = OrderResponse.model_validate(order)

    DB_QUERY_DURATION_SECONDS.labels(operation="create_order").observe(
        time.perf_counter() - t0
    )

    logger.info(
        "Order created successfully",
        extra={"order_id": order_data.id, "product_id": order_data.product_id},
    )
    return order_data


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Get order by ID",
)
async def get_order(order_id: int) -> OrderResponse:
    """Retrieve an order by ID."""
    t0 = time.perf_counter()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Order).where(Order.id == order_id)
        )
        order = result.scalar_one_or_none()

    DB_QUERY_DURATION_SECONDS.labels(operation="get_order").observe(
        time.perf_counter() - t0
    )

    if not order:
        logger.warning("Order not found", extra={"order_id": order_id})
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found",
        )

    return OrderResponse.model_validate(order)

import logging
import time
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.inventory import (
    InventoryClient,
    InventoryDownstreamError,
    InventoryTimeoutError,
    InventoryUnavailableError,
)
from app.config import Settings, get_settings
from app.database import acquire_db_connection
from app.metrics import DB_OPERATION_DURATION_SECONDS
from app.models import Order
from app.schemas import OrderCreate, OrderResponse

logger = logging.getLogger("orderflow.orders")
router = APIRouter(prefix="/orders", tags=["orders"])


def get_inventory_client(
    settings: Settings = Depends(get_settings),
) -> InventoryClient:
    """Dependency providing a configured InventoryClient."""
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
    """Healthy Order creation flow with separated connection wait and execution instrumentation:

    1. Check inventory availability via external HTTP call (NO DB connection held).
    2. After inventory succeeds, explicitly acquire physical DB connection from pool.
    3. Execute DB transaction / insert and flush on the acquired connection.
    4. Commit and release physical DB connection back to pool.
    5. Return created order with stage timings logged.
    """
    t_req_start = time.perf_counter()
    logger.info(
        "Initiating order creation",
        extra={"product_id": payload.product_id, "quantity": payload.quantity},
    )

    # Step 1: Check downstream inventory FIRST (no DB connection held)
    t_inv_start = time.perf_counter()
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
    inventory_ms = round((time.perf_counter() - t_inv_start) * 1000, 2)

    # Step 2: Explicitly acquire physical DB connection from pool (measures wait time)
    try:
        async with acquire_db_connection() as (conn, wait_seconds):
            db_wait_ms = round(wait_seconds * 1000, 2)

            # Step 3: Execute DB operations within transaction using acquired connection
            t_exec_start = time.perf_counter()
            async with conn.begin():
                async with AsyncSession(bind=conn, expire_on_commit=False) as session:
                    order = Order(
                        product_id=payload.product_id,
                        quantity=payload.quantity,
                        status="CONFIRMED",
                    )
                    session.add(order)
                    await session.flush()
                    order_data = OrderResponse.model_validate(order)
            db_exec_ms = round((time.perf_counter() - t_exec_start) * 1000, 2)
            DB_OPERATION_DURATION_SECONDS.labels(operation="create_order").observe(
                db_exec_ms / 1000.0
            )

    except SQLAlchemyTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection pool timeout",
        ) from exc

    total_ms = round((time.perf_counter() - t_req_start) * 1000, 2)

    logger.info(
        "Order created successfully",
        extra={
            "order_id": order_data.id,
            "product_id": order_data.product_id,
            "inventory_ms": inventory_ms,
            "db_wait_ms": db_wait_ms,
            "db_exec_ms": db_exec_ms,
            "total_ms": total_ms,
        },
    )
    return order_data


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Get order by ID",
)
async def get_order(order_id: int) -> OrderResponse:
    """Retrieve an order by ID with separated connection wait and query execution instrumentation."""
    try:
        async with acquire_db_connection() as (conn, wait_seconds):
            t_exec_start = time.perf_counter()
            async with AsyncSession(bind=conn, expire_on_commit=False) as session:
                result = await session.execute(
                    select(Order).where(Order.id == order_id)
                )
                order = result.scalar_one_or_none()
            db_exec_ms = round((time.perf_counter() - t_exec_start) * 1000, 2)
            DB_OPERATION_DURATION_SECONDS.labels(operation="get_order").observe(
                db_exec_ms / 1000.0
            )

    except SQLAlchemyTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection pool timeout",
        ) from exc

    if not order:
        logger.warning("Order not found", extra={"order_id": order_id})
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found",
        )

    return OrderResponse.model_validate(order)

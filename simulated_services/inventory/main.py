import asyncio
import os
from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="Simulated Inventory Service")

DEFAULT_LATENCY_MS = float(os.getenv("DEFAULT_LATENCY_MS", "0"))


class InventoryCheckRequest(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)


class InventoryCheckResponse(BaseModel):
    product_id: str
    available: bool
    stock: int


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "inventory-service"}


@app.post("/inventory/check", response_model=InventoryCheckResponse)
async def check_inventory(payload: InventoryCheckRequest, latency_ms: float | None = None):
    sleep_time_ms = latency_ms if latency_ms is not None else DEFAULT_LATENCY_MS
    if sleep_time_ms > 0:
        await asyncio.sleep(sleep_time_ms / 1000.0)

    # In baseline M0/M1, all products have stock available
    return InventoryCheckResponse(
        product_id=payload.product_id,
        available=True,
        stock=1000,
    )

import asyncio
import os
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

app = FastAPI(title="Simulated Inventory Service")

DEFAULT_LATENCY_MS = float(os.getenv("DEFAULT_LATENCY_MS", "0"))

# OpenTelemetry distributed tracing setup
otel_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
if otel_endpoint:
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        service_name = os.getenv("OTEL_SERVICE_NAME", "inventory-service")
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=f"{otel_endpoint.rstrip('/')}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    except Exception as e:
        import sys
        print(f"Failed to initialize tracing in inventory service: {e}", file=sys.stderr)


class InventoryCheckResponse(BaseModel):
    product_id: str
    available: bool
    stock: int


class InventoryCheckRequest(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "inventory-service"}


@app.get("/inventory/{product_id}", response_model=InventoryCheckResponse)
async def get_inventory(
    product_id: str,
    latency_ms: float | None = Query(default=None),
):
    """Check inventory for a product."""
    sleep_time_ms = latency_ms if latency_ms is not None else DEFAULT_LATENCY_MS
    if sleep_time_ms > 0:
        await asyncio.sleep(sleep_time_ms / 1000.0)

    # Simulated downstream failure cases
    if product_id.startswith("error-500"):
        raise HTTPException(
            status_code=500, detail="Downstream inventory internal error"
        )

    if product_id.startswith("timeout"):
        # Induce deliberate timeout beyond standard 5s client timeout
        await asyncio.sleep(10.0)

    if product_id.startswith("unavailable") or product_id.startswith("out-of-stock"):
        return InventoryCheckResponse(
            product_id=product_id,
            available=False,
            stock=0,
        )

    return InventoryCheckResponse(
        product_id=product_id,
        available=True,
        stock=1000,
    )


@app.post("/inventory/check", response_model=InventoryCheckResponse)
async def check_inventory(
    payload: InventoryCheckRequest, latency_ms: float | None = None
):
    """Backward-compatible endpoint for POST check."""
    return await get_inventory(payload.product_id, latency_ms=latency_ms)

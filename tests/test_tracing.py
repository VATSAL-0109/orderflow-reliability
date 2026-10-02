import json
import logging
import pytest
from httpx import AsyncClient
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from app.logging_config import JSONFormatter
from app.clients.inventory import InventoryClient


def test_json_formatter_includes_trace_id_when_span_active():
    """Verify that JSONFormatter injects trace_id and span_id when an OpenTelemetry span is active."""
    tracer = trace.get_tracer("test-tracer")
    formatter = JSONFormatter()

    with tracer.start_as_current_span("test-span"):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test log message",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        data = json.loads(formatted)

        assert "trace_id" in data
        assert "span_id" in data
        assert len(data["trace_id"]) == 32
        assert len(data["span_id"]) == 16
        assert data["trace_id"] != "0" * 32
        assert data["span_id"] != "0" * 16


def test_json_formatter_omits_trace_id_when_no_active_span():
    """Verify that JSONFormatter safely omits trace_id when no span is active."""
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="No span log message",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    data = json.loads(formatted)

    assert "trace_id" not in data
    assert "span_id" not in data


@pytest.mark.asyncio
async def test_order_creation_generates_db_spans(async_client: AsyncClient, monkeypatch):
    """Verify that POST /orders creates explicit spans for db.acquire_connection and db.execute_transaction."""
    memory_exporter = InMemorySpanExporter()
    processor = SimpleSpanProcessor(memory_exporter)
    provider = trace.get_tracer_provider()
    
    # Add in-memory span processor if supported by current provider
    if hasattr(provider, "add_span_processor"):
        provider.add_span_processor(processor)

    async def mock_check_inventory(self, product_id):
        return True

    monkeypatch.setattr(InventoryClient, "check_inventory", mock_check_inventory)

    response = await async_client.post(
        "/orders",
        json={"product_id": "trace-test-prod", "quantity": 2},
    )
    assert response.status_code == 201

    spans = memory_exporter.get_finished_spans()
    span_names = [s.name for s in spans]

    # Verify db.acquire_connection and db.execute_transaction spans were produced
    assert "db.acquire_connection" in span_names
    assert "db.execute_transaction" in span_names

    # Check span attributes
    acquire_span = next(s for s in spans if s.name == "db.acquire_connection")
    assert "db.wait_ms" in acquire_span.attributes

    exec_span = next(s for s in spans if s.name == "db.execute_transaction")
    assert "db.exec_ms" in exec_span.attributes
    assert "order.id" in exec_span.attributes

import logging
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger("orderflow.tracing")
tracer = trace.get_tracer("orderflow.api")


def setup_tracing(
    service_name: str = "orderflow-api",
    otlp_endpoint: str | None = None,
    enabled: bool = True,
) -> TracerProvider | None:
    """Initialize OpenTelemetry tracer provider and export to OTLP HTTP receiver (Jaeger)."""
    if not enabled:
        return None

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        traces_url = (
            otlp_endpoint
            if otlp_endpoint.endswith("/v1/traces")
            else f"{otlp_endpoint.rstrip('/')}/v1/traces"
        )
        try:
            exporter = OTLPSpanExporter(endpoint=traces_url)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("OpenTelemetry OTLP exporter configured", extra={"endpoint": traces_url})
        except Exception as exc:
            logger.warning("Failed to initialize OTLP exporter", extra={"error": str(exc)})

    trace.set_tracer_provider(provider)

    # Automatically instrument outgoing HTTPX calls to propagate W3C trace context
    try:
        HTTPXClientInstrumentor().instrument()
    except Exception as exc:
        logger.warning("Failed to instrument httpx with OpenTelemetry", extra={"error": str(exc)})

    return provider


def instrument_app(app) -> None:
    """Instrument FastAPI application with OpenTelemetry."""
    try:
        FastAPIInstrumentor.instrument_app(app)
    except Exception as exc:
        logger.warning("Failed to instrument FastAPI app with OpenTelemetry", extra={"error": str(exc)})

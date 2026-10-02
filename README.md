# OrderFlow — Production Reliability Engineering

An engineering assessment project simulating and investigating intermittent production reliability failures in an asynchronous microservice architecture.

## System Architecture (Baseline)

```text
Client / Load Test
        |
        v
   FastAPI API (:8000)
      /health  (Liveness)
      /ready   (Readiness - DB ping)
      /metrics (Prometheus scrape)
      /orders
        |
        +------ PostgreSQL (:5432)
        |
        +------ Simulated Inventory Service (:8001)

Monitoring Stack:
   Prometheus (:9090)  <-- Scrapes OrderFlow /metrics (5s interval)
   Grafana (:3000)     <-- Pre-provisioned Reliability Dashboard
```

## Milestone Roadmap

- **M0 — Repository/Project Setup**: Baseline containerization, configuration, dependencies, and project skeleton.
- **M1 — Healthy Service**: Full order creation flow, database migrations/tables, downstream inventory check, baseline integration tests.
- **M2 — Observability**: Structured JSON logging with request ID tracing, stage timings, Prometheus metrics (request rates, HTTP latencies, downstream inventory durations, separated DB connection acquisition wait vs. DB operation durations, and real-time connection pool state).
- **M3 — Deliberately Introduce Failure**: Database connection pool exhaustion caused by holding an acquired DB connection across downstream Inventory network I/O under constrained pool capacity (`pool_size=5`, `max_overflow=0`, `pool_timeout=3.0s`).
- **M4 — Diagnose Failure Using Evidence**: Evidence-driven debugging refuting incorrect hypotheses (slow SQL, downstream inventory failure) and isolating root-cause connection pool checkout timeouts.
- **M5 — Fix and Measure Improvement**: Restructured resource lifecycle (calling Inventory before DB connection checkout); proved 100% elimination of 503 timeouts under identical concurrency=40 load.
- **M6 — Production Monitoring & Prevention**: Prometheus scraping, Grafana dashboard, actionable alert rules, `/ready` health separation, and architectural regression guards.

## Observability & Operations (M6)

### 1. Available Metrics
The API exposes standard Prometheus metrics at `GET /metrics`:
- **HTTP Traffic & Latencies**: `http_requests_total` (by method, endpoint, status code), `http_request_duration_seconds` (histogram).
- **Downstream Inventory**: `inventory_request_duration_seconds` (histogram by status: `success`, `unavailable`, `error`, `timeout`).
- **Database Connection Acquisition**: `db_connection_wait_seconds` (histogram tracking duration spent in `QueuePool` waiting for a physical connection).
- **Database Operation Duration**: `db_operation_duration_seconds` (histogram measuring SQL execution, flush, and commit duration after connection acquisition).
- **Database Connection Pool State**: `db_pool_checked_out_connections`, `db_pool_available_connections`, `db_pool_overflow_connections` (gauges).
- **Pool Exhaustion Counter**: `db_pool_timeouts_total` (counter incremented on `sqlalchemy.exc.TimeoutError`).

### 2. Structured JSON Logging & Request ID Tracing
Every HTTP request generates a unique UUID `X-Request-ID` propagated through context variables and downstream HTTP headers.
Completed orders log explicit stage timing breakdowns:
```json
{
  "timestamp": "2026-10-02T07:18:13.681527+00:00",
  "level": "INFO",
  "logger": "orderflow.orders",
  "message": "Order created successfully",
  "request_id": "load-test-038",
  "extra": {
    "order_id": 116,
    "product_id": "laptop-038",
    "inventory_ms": 732.69,
    "db_wait_ms": 270.25,
    "db_exec_ms": 17.56,
    "total_ms": 1024.04
  }
}
```

### 3. Prometheus Setup & Alert Rules
Prometheus runs in Docker Compose (`:9090`) scraping `api:8000/metrics` every 5 seconds. Alert rules are defined in `monitoring/prometheus/alerts.yml`:
1. `DBPoolCheckoutTimeouts` (*Critical, for: 0m*): Fires immediately if `increase(db_pool_timeouts_total[1m]) > 0`. Any pool timeout directly drops user requests with HTTP 503.
2. `DBConnectionWaitHigh` (*Warning, for: 30s*): Fires if average DB connection checkout wait exceeds 500ms (`> 0.5s`), indicating pool saturation before timeouts occur.
3. `HighHTTP5xxRate` (*Critical, for: 1m*): Fires if 5xx error rate exceeds 5% of total traffic.
4. `InventoryLatencyHigh` (*Warning, for: 1m*): Fires if downstream inventory response latency exceeds 1.5s.

### 4. Grafana Reliability Dashboard
Grafana runs at `http://localhost:3000` (credentials: `admin`/`admin`) with automatic datasource and dashboard provisioning (`monitoring/grafana/orderflow-reliability-dashboard.json`).

The dashboard is designed to visually isolate three key failure scenarios:
- **Scenario A (Slow Database Operations)**: Panel J (`DB Operation Duration`) spikes, while Panel D (`DB Connection Wait Time`) remains low.
- **Scenario B (Slow Downstream Dependency)**: Panel I (`Downstream Inventory Latency`) spikes, while Panel J (`DB Operation Duration`) remains flat.
- **Scenario C (Connection Pool Contention / Starvation)**: Panel D (`DB Connection Wait Time`) and Panel E (`Checked Out Connections`) spike to maximum capacity, while Panel J (`DB Operation Duration`) remains fast (< 30ms). Under sustained load, Panel H (`DB Pool Timeouts`) and Panel B (`HTTP 5xx Rate`) fire.

### 5. Health vs. Readiness Semantics
- **Liveness (`/health`)**: Lightweight check verifying the event loop and HTTP server are responsive. Returns `200 OK` as long as the process is alive. If this fails, the container should be restarted.
- **Readiness (`/ready`)**: Verifies primary datastore connectivity via a lightweight `SELECT 1` ping. If PostgreSQL is starting up or disconnected, `/ready` returns `503 Service Unavailable`, preventing ingress traffic without restarting the container.
- **Dependency Health Decoupling**: Health and readiness checks deliberately do **not** depend on the external Inventory service. If downstream inventory is degraded, OrderFlow remains ready to serve reads (`GET /orders/{id}`) and handle inventory responses gracefully.

### 6. Architectural Prevention Guideline & Regression Protection
> [!IMPORTANT]
> **Core Reliability Rule**: Never hold a database connection or database transaction open across an external network I/O call (HTTP, gRPC, third-party API) unless there is a deliberate, documented architectural requirement.

**Why? (The M3 Failure Demonstration)**:
In M3, acquiring a DB connection before calling Inventory (~650ms) held the connection idle for 98% of its lifecycle. Under concurrency=40 with a pool size of 5, requests spent 2.7s+ waiting in the queue, exhausting the pool and causing 10 out of 40 requests to fail with HTTP 503.

**Regression Guard**:
The automated test [`test_create_order_resource_lifecycle`](tests/test_orders.py) enforces this ordering in CI by asserting that the inventory check completes strictly before any database connection checkout occurs.

---

## Incident Post-Mortem Summary (M3 vs. M5)

| Dimension | M3 (Deliberate Defect) | M5 (Reliability Fix) |
|---|---|---|
| **Resource Lifecycle** | Acquire DB connection $\rightarrow$ Call Inventory $\rightarrow$ Insert DB $\rightarrow$ Release | Call Inventory $\rightarrow$ Acquire DB connection $\rightarrow$ Insert DB $\rightarrow$ Release |
| **Connection Hold Time** | **~665ms – 770ms** (dominated by downstream network I/O) | **~15ms – 25ms** (only fast local SQL transaction) |
| **Concurrency 40 Results** | **30 OK (75%), 10 Failed (25% HTTP 503)** | **40 OK (100%), 0 Failed (0% HTTP 503)** |
| **DB Pool Timeouts** | **+10 timeouts** (`db_pool_timeouts_total`) | **0 timeouts** |
| **Queue Wait Time** | Escalated to **2,733ms** (breached 3.0s pool timeout) | Dropped to **~250ms – 270ms** across all tail requests |
| **Total Test Duration** | 4.43 seconds | 1.52 seconds (2.9x throughput speedup) |

---

## Distributed Tracing (M6.1 — OpenTelemetry & Jaeger)

To complement structured logs, request IDs, metrics, and Grafana dashboards, OrderFlow implements distributed tracing using **OpenTelemetry** and a local **Jaeger** trace backend.

### 1. Architecture & Local Backend
- **Jaeger Service**: Runs via Docker Compose (`jaegertracing/all-in-one:1.56`) with OTLP receivers on port `4317` (gRPC) and `4318` (HTTP), and the web UI on [http://localhost:16686](http://localhost:16686).
- **Zero Heavy Infrastructure**: Uses standard OpenTelemetry Python SDK with `OTLPSpanExporter` streaming directly to Jaeger without external agents, collectors, or SaaS dependencies.

### 2. Spans Captured During `POST /orders`
Every order creation workflow produces a hierarchical trace detailing all critical processing stages:

```
[orderflow-api] POST /orders  (Root span: total request duration)
  │
  ├── [orderflow-api] GET http://inventory-service:8001/inventory/{product_id} (HTTPX downstream call)
  │     └── [inventory-service] GET /inventory/{product_id} (W3C traceparent propagated downstream span)
  │
  └── [orderflow-api] db.acquire_connection  (DB connection checkout from pool; tag: db.wait_ms)
        └── [orderflow-api] db.execute_transaction  (INSERT + flush + commit; tags: db.exec_ms, order.id)
```

1. **Incoming HTTP Request**: Captured automatically via `FastAPIInstrumentor`.
2. **Downstream Inventory HTTP Call**: Captured via `HTTPXClientInstrumentor`, which automatically injects W3C `traceparent` headers into outgoing requests.
3. **Downstream Inventory Execution**: Simulated inventory service receives the trace context and records its internal latency and execution as a direct child span.
4. **Database Connection Acquisition**: Focused manual span `db.acquire_connection` recording `db.wait_ms`.
5. **Database Transaction Execution**: Focused manual span `db.execute_transaction` recording `db.exec_ms` and `order.id` (omits sensitive SQL parameters).

### 3. Trace Context & Structured Log Correlation
The application maintains correlation between log records and traces:
- **`request_id`**: Injected into every log entry from `request_id_ctx` (and returned in the `X-Request-ID` response header).
- **`trace_id` & `span_id`**: Automatically extracted by `JSONFormatter` from active OpenTelemetry spans and included in every structured log line:
```json
{
  "timestamp": "2026-10-02T08:10:25.229774+00:00",
  "level": "INFO",
  "logger": "orderflow.orders",
  "message": "Order created successfully",
  "request_id": "6b7c9dac-d69b-4291-9ecb-3f963e108e8b",
  "trace_id": "0e4227b9841bd1b6d7b74dea52a91f7c",
  "span_id": "1a00f2381622d1a4",
  "extra": {
    "order_id": 213,
    "product_id": "prod-test-tracing-2",
    "inventory_ms": 761.68,
    "db_wait_ms": 1.52,
    "db_exec_ms": 24.49,
    "total_ms": 788.84
  }
}
```
An operator can take any `trace_id` from Jaeger to find all matching logs, or take a `request_id` from an error report and view its exact visual trace timeline in Jaeger.

### 4. Diagnosing Failure Modes via Tracing vs. Metrics/Logs
While M3's failure can be diagnosed via Prometheus metrics (`db_connection_wait_seconds`, `db_pool_timeouts_total`) and structured logs, distributed traces provide an intuitive **visual view** of the resource lifecycle:

| Bottleneck / Scenario | Trace Visual Signature | Metric Confirmation |
|---|---|---|
| **Slow Inventory** | Long span on `GET http://inventory-service...` with normal/fast subsequent spans. | `inventory_request_duration_seconds` high; `db_connection_wait_seconds` low. |
| **Slow DB Query/Commit** | `db.acquire_connection` is fast, but child span `db.execute_transaction` is prolonged. | `db_operation_duration_seconds` high; `db_connection_wait_seconds` low. |
| **DB Connection Starvation** | `db.acquire_connection` span is prolonged with high `db.wait_ms` tag (> 3000ms), while `db.execute_transaction` is fast (~10ms). | `db_connection_wait_seconds` high; `db_pool_checked_out_connections=5`; `db_pool_timeouts_total` increments. |

### 5. Visualizing the M3 vs. M5 Resource Lifecycle
- **M3 (Defective Lifecycle)**:
  ```
  POST /orders
    ├── db.acquire_connection (acquires DB connection)
    │     ├── GET http://inventory-service (~650ms holding DB connection!)
    │     └── db.execute_transaction (~15ms)
  ```
- **M5 (Reliable Lifecycle)**:
  ```
  POST /orders
    ├── GET http://inventory-service (~650ms, NO DB connection held)
    └── db.acquire_connection (acquires DB connection only when ready to write)
          └── db.execute_transaction (~15ms, released immediately)
  ```

---

## Quickstart & Verification

### 1. Start Services via Docker Compose
```bash
docker compose up --build -d
```

### 2. Verify Health & Observability Backends
- **Main API Liveness**: `curl -i http://localhost:8000/health`
- **Main API Readiness**: `curl -i http://localhost:8000/ready`
- **Prometheus Targets**: [http://localhost:9090/targets](http://localhost:9090/targets)
- **Grafana Dashboard**: [http://localhost:3000](http://localhost:3000) (admin / admin)
- **Jaeger Trace UI**: [http://localhost:16686](http://localhost:16686) (Service: `orderflow-api`)

### 3. Run Automated Tests & Load Tests
```bash
# Run full pytest suite (23 tests including unit, integration, and tracing)
pytest -v

# Verify Jaeger distributed trace ingestion
python scripts/verify_traces.py

# Run Concurrency=40 Load Verification (Zero timeouts under M5 constraints)
python scripts/load_test.py 40
```

### 4. Stop Containers
```bash
docker compose down -v
```

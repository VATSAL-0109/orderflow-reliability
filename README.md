# OrderFlow — Production Reliability Engineering

An end-to-end reliability engineering project diagnosing, instrumenting, investigating, and resolving an intermittent production failure in an asynchronous order processing microservice.

---

## 1. Project Overview

OrderFlow is an asynchronous order-processing service built to demonstrate practical reliability engineering practices. The service receives order requests, validates inventory with a downstream dependency, persists confirmed orders into PostgreSQL, and exposes comprehensive observability across logs, metrics, health checks, alerts, dashboards, and distributed traces.

This project documents the complete diagnostic journey: from deliberate defect introduction (database connection pool starvation) to evidence-driven investigation, hypothesis testing, root-cause remediation, monitoring/alert provisioning, and automated regression prevention.

---

## 2. Problem Statement

Under concurrent order placement, OrderFlow exhibited intermittent **HTTP 503 Service Unavailable** errors.
- **Symptom**: Under a modest concurrent burst of 40 requests (`concurrency=40`), 10 out of 40 requests (25%) failed with HTTP 503.
- **Impact**: Lost customer orders, degraded service availability, and unbounded tail latency for successful requests.
- **Challenge**: Initial surface symptoms gave conflicting impressions—either the downstream inventory microservice was failing or the PostgreSQL database was struggling under load.

---

## 3. System Architecture

```text
                               +--------------------------+
                               |    Client / Load Test    |
                               +--------------------------+
                                            │
                                            │ HTTP (X-Request-ID, W3C Traceparent)
                                            ▼
                           +───────────────────────────────────+
                           |     OrderFlow API (:8000)         |
                           |  - FastAPI (Python 3.12 async)    |
                           |  - Async SQLAlchemy / asyncpg     |
                           |  - OpenTelemetry Instrumentation  |
                           +───────────────────────────────────+
                                    │                 │
                1. Check Inventory  │                 │ 2. Persist Order (Short Tx)
          (HTTPX / ~600ms latency)  │                 │ (QueuePool: 5 conns, 3.0s timeout)
                                    ▼                 ▼
             +────────────────────────────+     +──────────────────────────+
             | Simulated Inventory (:8001)|     |    PostgreSQL (:5432)    |
             | - Fast availability check  |     | - Persistent order table |
             | - OpenTelemetry trace node |     | - Health check ping      |
             +────────────────────────────+     +──────────────────────────+

                               OBSERVABILITY PIPELINE
                               ──────────────────────
      OrderFlow API (:8000) ───[Scrape /metrics every 5s]───► Prometheus (:9090)
            │                                                      │
            │                                                      ▼
            │                                              Grafana (:3000)
            │                                        (Reliability Dashboard)
            │
            └───[Export OTLP Spans via HTTP :4318]──────────► Jaeger (:16686)
                                                        (Distributed Tracing)
```

---

## 4. Technology Stack

- **Application Core**: Python 3.12, FastAPI, Pydantic v2, Uvicorn (ASGI)
- **Database & Persistence**: PostgreSQL 16 (Alpine), SQLAlchemy 2.0 (asyncio extension), `asyncpg` async driver
- **HTTP Client**: `httpx` (async client with timeout management)
- **Metrics & Telemetry**: Prometheus Client Python SDK, OpenTelemetry API & SDK (`opentelemetry-exporter-otlp-proto-http`, `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-httpx`)
- **Monitoring & Visualization**: Prometheus 2.51.0, Grafana 10.4.1 (pre-provisioned datasource & dashboard), Jaeger All-in-One 1.56
- **Containerization & Orchestration**: Docker, Docker Compose
- **Testing & Tooling**: Pytest, Pytest-Asyncio, custom concurrency load drivers

---

## 5. Setup & Prerequisites

### Prerequisites
- Docker Engine 24.0+ and Docker Compose v2+
- Python 3.12+ (for running test scripts locally)

### Local Environment Setup
```bash
# Clone the repository
git clone https://github.com/VATSAL-0109/orderflow-reliability.git
cd orderflow-reliability

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install development and testing dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Copy example environment configuration
cp .env.example .env
```

---

## 6. Running the Service

Start the complete environment (PostgreSQL, Inventory Service, OrderFlow API, Prometheus, Grafana, and Jaeger) with a single command:

```bash
docker compose up --build -d
```

### Verification
```bash
# Verify container states
docker compose ps

# Check API health
curl -s http://localhost:8000/health
# Response: {"status":"healthy","service":"OrderFlow"}

# Check database readiness
curl -s http://localhost:8000/ready
# Response: {"status":"ready","database":"connected"}
```

---

## 7. API Endpoints

| Method | Endpoint | Description | Status Codes |
|---|---|---|---|
| `POST` | `/orders` | Place a new customer order | `201 Created`, `409 Conflict`, `422 Unprocessable`, `502 Bad Gateway`, `503 Service Unavailable`, `504 Gateway Timeout` |
| `GET` | `/orders/{order_id}` | Retrieve order details by ID | `200 OK`, `404 Not Found` |
| `GET` | `/health` | Liveness probe (process responsive) | `200 OK` |
| `GET` | `/ready` | Readiness probe (`SELECT 1` DB ping) | `200 OK`, `503 Service Unavailable` |
| `GET` | `/metrics` | Prometheus metrics scrape endpoint | `200 OK` |

---

## 8. Observability Architecture

The observability stack adheres to the three pillars of telemetry, enriched by request IDs and decoupled health probes:

1. **Structured JSON Logs**: Formatted with ISO-8601 UTC timestamps, logger name, log level, event message, `request_id`, `trace_id`, `span_id`, and timing payloads (`inventory_ms`, `db_wait_ms`, `db_exec_ms`).
2. **Request ID Correlation**: Every request receives or generates a unique `X-Request-ID` via middleware, stored in an async context variable (`contextvars.ContextVar`) and included in all downstream logs and HTTP response headers.
3. **Prometheus Metrics**: High-resolution metrics exposed on `/metrics` tracking traffic, HTTP latencies, connection pool gauges, checkout wait times, and pool exhaustion counters.
4. **Distributed Tracing**: End-to-end W3C trace propagation linking OrderFlow API incoming calls, HTTPX downstream inventory calls, remote inventory execution, and explicit database spans into a single trace graph.

---

## 9. Failure Reproduction (The M3 Defect)

To investigate the failure scientifically, the system was subjected to a controlled, reproducible failure scenario under constrained resources:
- **Pool Size**: `DB_POOL_SIZE = 5`
- **Max Overflow**: `DB_MAX_OVERFLOW = 0`
- **Checkout Timeout**: `DB_POOL_TIMEOUT = 3.0s`
- **Downstream Inventory Latency**: `600ms – 700ms`
- **Concurrent Load**: `concurrency = 40`

### Defective Lifecycle Introduced in M3:
```text
POST /orders
  1. Acquire physical DB connection from QueuePool (Hold connection)
  2. Call downstream Inventory service (~650ms network I/O)
  3. Execute SQL INSERT + Commit (~15ms)
  4. Release DB connection back to QueuePool
```

### Observed Symptoms Under Concurrency=40:
- **Throughput**: 30 requests succeeded (`HTTP 201`), **10 requests failed (`HTTP 503`)**.
- **Pool Timeouts**: `db_pool_timeouts_total` increased by exactly **10**.
- **Tail Wait Duration**: Max observed DB wait among successful requests reached approximately **2,708ms – 2,733ms**. Later requests exceeded the 3.0s DB pool checkout timeout and returned HTTP 503.

---

## 10. Investigation Process (M4)

The investigation followed an evidence-driven triage methodology without prior assumptions:
1. **Analyze Error Signatures**: HTTP 503 responses returned `{"detail": "Database connection pool exhausted. Please retry later."}`.
2. **Correlate Log Streams**: Inspected structured JSON logs matching failed request IDs.
3. **Inspect Prometheus Metrics**: Evaluated `db_pool_checked_out_connections`, `db_connection_wait_seconds`, `db_operation_duration_seconds`, and `inventory_request_duration_seconds`.
4. **Formulate and Systematically Test Hypotheses**.

---

## 11. Wrong Hypothesis #1: "Database Query Execution is Slow"

- **Hypothesis**: PostgreSQL query execution or transaction commits are slowing down under concurrency, holding connections open and creating a backlog.
- **Evidence Gathered**:
  - `db_operation_duration_seconds` metric: Median execution duration was **12ms – 18ms** across all requests.
  - Application logs: `db_exec_ms` consistently logged between **11ms and 24ms**, never exceeding 30ms.
- **Conclusion**: **REJECTED**. The database engine was executing queries rapidly and had ample capacity. SQL execution was not the bottleneck.

---

## 12. Wrong Hypothesis #2: "Downstream Inventory Service is Failing"

- **Hypothesis**: The inventory microservice is returning 5xx errors or crashing, causing OrderFlow to return 503s to clients.
- **Evidence Gathered**:
  - Inventory metrics: `inventory_request_duration_seconds{status="success"}` accounted for 100% of calls.
  - Inventory logs: Simulated service logged HTTP 200 OK for every single check.
  - Error logs: None of the failed orders logged `InventoryDownstreamError` or `InventoryTimeoutError`.
- **Conclusion**: **REJECTED**. Inventory checks were completely healthy and returning valid stock availability.

---

## 13. Root Cause Analysis

The true failure was **connection pool starvation caused by an inverted resource lifecycle**:
- The application acquired a physical database connection **before** initiating the downstream network call to the inventory service.
- Each connection was held idle for **~650ms** while waiting for external network I/O.
- With `DB_POOL_SIZE = 5` and zero overflow, the five available connections were held for approximately the downstream call duration plus DB execution (~670ms total).
- When 40 requests arrived concurrently, incoming requests queued in memory waiting for connections to be checked back in.
- As connection hold times accumulated across queued requests, wait times escalated until requests at the tail of the queue exceeded the `3.0s` `DB_POOL_TIMEOUT`, throwing `sqlalchemy.exc.TimeoutError` and returning HTTP 503.

---

## 14. Root Cause Fix (M5)

The fix decoupled external network I/O from database connection acquisition:

```python
# Step 1: Perform downstream inventory check FIRST (holding NO database resources)
await inventory_client.check_inventory(payload.product_id)

# Step 2: Acquire physical DB connection ONLY when ready to write
async with acquire_db_connection() as (conn, wait_seconds):
    # Step 3: Fast, atomic transactional write (~15ms)
    async with conn.begin():
        async with AsyncSession(bind=conn, expire_on_commit=False) as session:
            order = Order(
                product_id=payload.product_id,
                quantity=payload.quantity,
                status="CONFIRMED",
            )
            session.add(order)
            await session.flush()
# Step 4: Connection is automatically released back to pool
```

In the fixed flow, connections are held for only **~15ms** instead of **~670ms** during the order transaction—reducing connection hold time by approximately 98%.

---

## 15. Before vs. After Evidence

| Metric / Dimension | M3 (Deliberate Defect) | M5 (Reliability Fix) | Observation in Test Workload |
|---|---|---|---|
| **Resource Sequence** | Acquire DB $\rightarrow$ Call Inventory $\rightarrow$ Insert DB | Call Inventory $\rightarrow$ Acquire DB $\rightarrow$ Insert DB | Decoupled network I/O |
| **Connection Hold Time** | **~665ms – 770ms** | **~12ms – 25ms** | **~98% reduction in hold time** |
| **Concurrency 40 Success** | 30 OK / 10 Failed (75%) | **40 OK / 0 Failed (100% in test)** | **Zero HTTP 503 errors under test workload** |
| **DB Pool Timeouts** | **+10 timeouts** | **0 timeouts** | **Zero timeouts under test workload** |
| **Max Queue Wait Time** | **~2,733ms** (max observed wait among successful requests; later requests timed out > 3.0s) | **~39ms – 120ms** | **Substantial reduction in wait time** |
| **Total Test Duration** | 4.43 seconds | **1.24 – 1.71 seconds** | **~2.6x – 3.5x throughput gain** |

---

## 16. Prometheus & Grafana Monitoring (M6)

### Alert Rules (`monitoring/prometheus/alerts.yml`)
1. `DBPoolCheckoutTimeouts` (*Severity: Critical*): Fires immediately if `increase(db_pool_timeouts_total[1m]) > 0`. Directly flags dropped customer requests.
2. `DBConnectionWaitHigh` (*Severity: Warning*): Fires if average connection checkout wait exceeds 500ms (`> 0.5s`), providing proactive warning of pool contention before timeouts occur.
3. `HighHTTP5xxRate` (*Severity: Critical*): Fires if 5xx errors exceed 5% of total traffic.
4. `InventoryLatencyHigh` (*Severity: Warning*): Fires if downstream inventory latency exceeds 1.5s.

### Grafana Dashboard (`http://localhost:3000`)
Pre-provisioned dashboard displaying 10 diagnostic panels:
- **Panel A**: Order Creation Throughput & Success Rate
- **Panel B**: HTTP 5xx Error Rate
- **Panel C**: API Request Latency (p50, p95, p99)
- **Panel D**: DB Connection Acquisition Wait Time
- **Panel E**: Active vs. Available Pool Connections
- **Panel F**: Pool Saturation (% checked out)
- **Panel G**: Connection Pool Overflow
- **Panel H**: Database Pool Checkout Timeouts (Cumulative)
- **Panel I**: Downstream Inventory Call Latency
- **Panel J**: DB Operation Execution Duration

---

## 17. OpenTelemetry & Jaeger Tracing (M6.1)

OrderFlow implements distributed tracing using the OpenTelemetry Python SDK with export to local Jaeger:
- **Jaeger UI**: [http://localhost:16686](http://localhost:16686)
- **OTLP Endpoint**: `http://localhost:4318/v1/traces`

### Span Tree (`POST /orders`)
```text
[orderflow-api] POST /orders  (Root span: total request duration)
  │
  ├── [orderflow-api] GET http://inventory-service:8001/inventory/{product_id} (HTTPX downstream call)
  │     └── [inventory-service] GET /inventory/{product_id} (W3C traceparent propagated child span)
  │
  └── [orderflow-api] db.acquire_connection  (DB connection checkout; tag: db.wait_ms)
        └── [orderflow-api] db.execute_transaction  (INSERT + commit; tags: db.exec_ms, order.id)
```

### Visualizing Failures in Traces
- **Slow Inventory**: Prolonged span on `GET http://inventory-service...`; DB spans remain normal.
- **Slow Database**: Fast connection acquisition, prolonged `db.execute_transaction` span.
- **Connection Contention**: `db.acquire_connection` span is prolonged with high `db.wait_ms`, while `db.execute_transaction` is fast (~15ms).

---

## 18. Prevention & Regression Protection

### Architectural Rule
> [!IMPORTANT]
> **Core Reliability Invariant**: Never hold a database connection or transaction open across an external network I/O call (HTTP, gRPC, third-party API) unless strictly required for atomic distributed transactions (e.g. 2PC).

### Automated Regression Guard
The automated regression test [`test_create_order_resource_lifecycle`](tests/test_orders.py) asserts that downstream inventory validation completes strictly before `acquire_db_connection()` is invoked. Any code change that reintroduces connection checkout before network I/O will fail the test suite immediately.

---

## 19. Testing & Validation

### Run Full Pytest Suite (23 Tests)
```bash
pytest -v
```
Covers:
- Liveness and readiness semantics
- Metrics exposure and gauge updates
- Distributed tracing span generation and log correlation
- Inventory error handling (409 Conflict, 502 Bad Gateway, 504 Gateway Timeout)
- Input validation (422 Unprocessable Entity)
- Resource lifecycle regression prevention

### Run Load Verification Script
```bash
# Execute concurrency=40 workload against running stack
python scripts/load_test.py 40

# Verify Jaeger distributed trace capture
python scripts/verify_traces.py

# Verify Prometheus targets, rules, and Grafana datasource
python scripts/verify_monitoring.py
```

---

## 20. Limitations & Production Considerations

1. **Local In-Memory Trace Storage**: Jaeger runs in `all-in-one` mode with in-memory storage. For multi-node production, replace with OpenTelemetry Collector sending to OpenSearch, Tempo, or managed cloud tracing.
2. **Single Database Pool**: The pool is currently constrained per-process. In a horizontally autoscaling cluster, pool sizing must consider total aggregate connections across all replicas against PostgreSQL `max_connections`.
3. **Synchronous Workflow**: Order creation is currently synchronous HTTP request-response. Under extreme scale, decoupling via asynchronous message queues (e.g. Kafka, RabbitMQ) with saga patterns would prevent downstream latency spikes from impacting API threads.
4. **Basic Auth for Dashboards**: Grafana uses default local credentials (`admin`/`admin`) appropriate for isolated local development; production deployments should integrate SSO/OIDC.

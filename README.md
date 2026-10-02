# OrderFlow — Production Reliability Engineering

An engineering assessment project simulating and investigating intermittent production reliability failures in an asynchronous microservice architecture.

## System Architecture (Baseline)

```text
Client / Load Test
        |
        v
   FastAPI API (:8000)
      /health
      /metrics
      /orders (planned in M1)
        |
        +------ PostgreSQL (:5432)
        |
        +------ Simulated Inventory Service (:8001)
```

## Milestone Roadmap

- **M0 — Repository/Project Setup**: Baseline containerization, configuration, dependencies, and project skeleton.
- **M1 — Healthy Service**: Full order creation flow, database migrations/tables, downstream inventory check, baseline integration tests.
- **M2 — Observability** *(Complete)*: Structured JSON logging with request ID tracing, stage timings, Prometheus metrics (request rates, HTTP latencies, downstream inventory durations, separated DB connection acquisition wait vs. DB operation durations, and real-time connection pool state).
- **M3 — Deliberately Introduce Failure**: Connection pool contention under downstream latency.
- **M4 — Diagnose Failure Using Evidence**: Triangulating logs and metrics to pinpoint root cause.
- **M5 — Fix and Measure Improvement**: Decoupling connection lifecycle, demonstrating recovery.
- **M6 — Production Hardening**: Defensive timeouts, circuit breakers, and connection pool safeguards.
- **M7 — README / Submission Preparation**: Comprehensive technical post-mortem report and developer guide.

## Observability Architecture (M2)

### 1. Database Connection Separation
To accurately diagnose connection pool starvation in M3/M4, database timing is decoupled into two separate measurements:
- `db_connection_wait_seconds`: Time spent waiting to acquire a physical database connection from the pool (`QueuePool`).
- `db_operation_duration_seconds`: Time spent performing database operations once the connection is acquired (transaction begin, SQL execution, flush, and commit).

### 2. Request Stage Timing Breakdown
Structured JSON logs for completed orders include explicit stage measurements:
- `inventory_ms`: Actual downstream HTTP call duration.
- `db_wait_ms`: Actual pool connection checkout wait duration.
- `db_exec_ms`: Actual database operation duration (flush + commit).
- `total_ms`: End-to-end request duration.

*Note on timing verification*: The explicitly measured stages account for almost all of the total request duration, with the remaining difference representing uninstrumented application and framework overhead (routing, middleware, JSON serialization).

## Quickstart & Verification (M0)

### 1. Environment Setup
```bash
cp .env.example .env
```

### 2. Start Services via Docker Compose
```bash
docker compose up --build -d
```

### 3. Check Service Status & Logs
```bash
docker compose ps
docker compose logs -f api
```

### 4. Verify Health Endpoints
```bash
# Main API
curl -i http://localhost:8000/health

# Simulated Inventory Service
curl -i http://localhost:8001/health

# Prometheus Metrics Scrape Endpoint
curl -i http://localhost:8000/metrics
```

### 5. Stop Containers
```bash
docker compose down -v
```

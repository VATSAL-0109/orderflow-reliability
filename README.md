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

- **M0 — Repository/Project Setup** *(Current)*: Baseline containerization, configuration, dependencies, and project skeleton.
- **M1 — Healthy Service**: Full order creation flow, database migrations/tables, downstream inventory check, baseline integration tests.
- **M2 — Observability**: Structured JSON logging, Prometheus metrics (request rates, latencies, DB query durations, downstream durations).
- **M3 — Deliberately Introduce Failure**: Connection pool contention under downstream latency.
- **M4 — Diagnose Failure Using Evidence**: Triangulating logs and metrics to pinpoint root cause.
- **M5 — Fix and Measure Improvement**: Decoupling connection lifecycle, demonstrating recovery.
- **M6 — Production Hardening**: Defensive timeouts, circuit breakers, and connection pool safeguards.
- **M7 — README / Submission Preparation**: Comprehensive technical post-mortem report and developer guide.

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

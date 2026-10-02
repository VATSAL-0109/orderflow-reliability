from prometheus_client import Counter, Gauge, Histogram

# HTTP metrics
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total count of HTTP requests",
    ["method", "endpoint", "status"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

HTTP_ERRORS_TOTAL = Counter(
    "http_errors_total",
    "Total count of HTTP request errors (status >= 400)",
    ["method", "endpoint", "status_code"],
)

# Downstream Inventory metrics
INVENTORY_REQUEST_DURATION_SECONDS = Histogram(
    "inventory_request_duration_seconds",
    "Duration of downstream inventory requests in seconds",
    ["status"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
)

# Database Connection Wait vs Execution metrics
DB_CONNECTION_WAIT_SECONDS = Histogram(
    "db_connection_wait_seconds",
    "Duration waiting to acquire a physical database connection from the pool in seconds",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

DB_OPERATION_DURATION_SECONDS = Histogram(
    "db_operation_duration_seconds",
    "Duration of database operations in seconds after connection acquisition, including transaction and commit",
    ["operation"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)

# Real-Time Database Connection Pool Gauges
DB_POOL_CHECKED_OUT_CONNECTIONS = Gauge(
    "db_pool_checked_out_connections",
    "Number of database connections currently checked out from the pool",
)

DB_POOL_AVAILABLE_CONNECTIONS = Gauge(
    "db_pool_available_connections",
    "Number of database connections currently available (idle) in the pool",
)

DB_POOL_OVERFLOW_CONNECTIONS = Gauge(
    "db_pool_overflow_connections",
    "Number of active overflow database connections currently in use",
)

# Database Connection Pool Timeout Counter
DB_POOL_TIMEOUTS_TOTAL = Counter(
    "db_pool_timeouts_total",
    "Total count of connection pool acquisition timeouts",
)

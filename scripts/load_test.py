import asyncio
import json
import re
import sys
import time
from collections import Counter
import httpx

API_URL = "http://localhost:8000"


def parse_prometheus_metrics(text: str) -> dict:
    metrics = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) == 2:
            key, val = parts
            try:
                metrics[key] = float(val)
            except ValueError:
                metrics[key] = val
    return metrics


async def send_order(client: httpx.AsyncClient, index: int) -> dict:
    req_id = f"load-test-{index:03d}"
    start = time.perf_counter()
    try:
        resp = await client.post(
            f"{API_URL}/orders",
            json={"product_id": f"laptop-{index:03d}", "quantity": 1},
            headers={"X-Request-ID": req_id},
            timeout=30.0,
        )
        elapsed = time.perf_counter() - start
        return {
            "index": index,
            "request_id": req_id,
            "status_code": resp.status_code,
            "latency": elapsed,
            "detail": resp.json() if resp.status_code != 201 else resp.json().get("id"),
        }
    except Exception as e:
        elapsed = time.perf_counter() - start
        return {
            "index": index,
            "request_id": req_id,
            "status_code": 0,
            "latency": elapsed,
            "error": str(e),
        }


async def run_load_test(concurrency: int):
    print(f"=== Starting Load Test with concurrency={concurrency} ===")
    
    async with httpx.AsyncClient() as client:
        # Fetch initial metrics
        m_before_resp = await client.get(f"{API_URL}/metrics")
        m_before = parse_prometheus_metrics(m_before_resp.text)
        timeouts_before = m_before.get("db_pool_timeouts_total", 0.0)

        # Run concurrent requests
        start_time = time.perf_counter()
        tasks = [send_order(client, i) for i in range(1, concurrency + 1)]
        results = await asyncio.gather(*tasks)
        total_time = time.perf_counter() - start_time

        # Allow pool gauges to settle / refresh metrics
        await asyncio.sleep(0.5)
        m_after_resp = await client.get(f"{API_URL}/metrics")
        m_after = parse_prometheus_metrics(m_after_resp.text)
        timeouts_after = m_after.get("db_pool_timeouts_total", 0.0)

    # Analyze results
    status_counts = Counter(r["status_code"] for r in results)
    latencies = [r["latency"] for r in results]
    latencies.sort()

    print(f"\n--- Results Summary (Total time: {total_time:.2f}s) ---")
    print(f"Status codes: {dict(status_counts)}")
    print(f"Min latency: {latencies[0]:.3f}s")
    print(f"Median latency: {latencies[len(latencies)//2]:.3f}s")
    print(f"P95 latency: {latencies[int(len(latencies)*0.95)]:.3f}s")
    print(f"Max latency: {latencies[-1]:.3f}s")
    print(f"\nDB Pool Timeouts (Metric diff): before={timeouts_before}, after={timeouts_after}, diff={timeouts_after - timeouts_before}")

    print("\nSample Responses:")
    for r in results[:5]:
        print(f"  Req {r['request_id']}: status={r['status_code']} latency={r['latency']:.3f}s detail={r.get('detail')}")
    if status_counts.get(503, 0) > 0:
        failing = [r for r in results if r["status_code"] == 503]
        print(f"\nSample 503 Failure ({len(failing)} total):")
        for r in failing[:3]:
            print(f"  Req {r['request_id']}: status={r['status_code']} latency={r['latency']:.3f}s detail={r.get('detail')}")

    print("\nRelevant Metrics After Run:")
    for k in sorted(m_after.keys()):
        if any(needle in k for needle in ["db_pool", "db_connection_wait", "db_operation", "http_requests_total"]):
            print(f"  {k} = {m_after[k]}")

    return {
        "concurrency": concurrency,
        "status_counts": dict(status_counts),
        "timeouts_delta": timeouts_after - timeouts_before,
        "results": results,
    }


if __name__ == "__main__":
    concurrency = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    asyncio.run(run_load_test(concurrency))

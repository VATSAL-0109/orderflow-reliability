import json
import sys
import urllib.request


def inspect_trace(trace_id: str | None = None, operation: str | None = None):
    if trace_id:
        url = f"http://localhost:16686/api/traces/{trace_id}"
    elif operation:
        url = f"http://localhost:16686/api/traces?service=orderflow-api&operation={urllib.parse.quote(operation)}&limit=5"
    else:
        url = "http://localhost:16686/api/traces?service=orderflow-api&operation=POST%20/orders&limit=5"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"Error fetching from Jaeger: {e}")
        return

    traces = data.get("data", [])
    if not traces:
        print(f"No traces found for query: {url}")
        return

    for idx, trace in enumerate(traces):
        tid = trace.get("traceID")
        spans = trace.get("spans", [])
        processes = trace.get("processes", {})

        print(f"\n=======================================================")
        print(f"TRACE {idx + 1}: {tid} ({len(spans)} spans received)")
        print(f"=======================================================")
        # Deduplicate spans by spanID
        seen_spans = {}
        for s in spans:
            seen_spans[s.get("spanID")] = s
        spans_sorted = sorted(seen_spans.values(), key=lambda s: s.get("startTime", 0))
        for s in spans_sorted:
            span_id = s.get("spanID")
            parent_refs = s.get("references", [])
            parent_id = parent_refs[0].get("spanID") if parent_refs else "ROOT"
            op = s.get("operationName")
            dur_ms = s.get("duration", 0) / 1000.0
            proc_id = s.get("processID")
            svc = processes.get(proc_id, {}).get("serviceName", "unknown")
            tags = {t["key"]: t["value"] for t in s.get("tags", [])}

            print(f"  [{svc}] {op} | {dur_ms:.2f}ms | span={span_id[:8]} parent={parent_id[:8] if parent_id != 'ROOT' else 'ROOT'}")
            for tag_name in ["http.method", "http.target", "http.url", "http.status_code", "db.wait_ms", "db.exec_ms", "order.id"]:
                if tag_name in tags:
                    print(f"      {tag_name}: {tags[tag_name]}")


if __name__ == "__main__":
    import urllib.parse
    trace_arg = sys.argv[1] if len(sys.argv) > 1 else None
    inspect_trace(trace_id=trace_arg)

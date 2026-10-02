import httpx
import json

def verify_all():
    with httpx.Client(timeout=10.0) as client:
        # 1. API Health & Ready
        r_health = client.get("http://localhost:8000/health")
        print("1. API /health:", r_health.status_code, r_health.json())
        r_ready = client.get("http://localhost:8000/ready")
        print("   API /ready:", r_ready.status_code, r_ready.json())

        # 2. Inventory Health
        r_inv = client.get("http://localhost:8001/health")
        print("2. Inventory /health:", r_inv.status_code, r_inv.json())

        # 3. Prometheus Scrape Target
        r_prom_targets = client.get("http://localhost:9090/api/v1/targets")
        targets = r_prom_targets.json()["data"]["activeTargets"]
        for t in targets:
            job = t["labels"].get("job", "unknown")
            health = t.get("health", "unknown")
            scrape_url = t.get("scrapeUrl", "")
            print(f"3. Prometheus Target [{job}]: health={health}, scrapeUrl={scrape_url}")

        # 4. Prometheus Rules / Alerts
        r_prom_rules = client.get("http://localhost:9090/api/v1/rules")
        rule_groups = r_prom_rules.json()["data"]["groups"]
        print(f"4. Prometheus Rule Groups loaded: {len(rule_groups)}")
        for g in rule_groups:
            print(f"   Group: '{g['name']}', rules: {len(g['rules'])}")
            for r in g["rules"]:
                print(f"     Rule: {r['name']} (state: {r['state']}, query: {r['query']})")

        # 5. Grafana Health & Datasources
        r_grafana_health = client.get("http://localhost:3000/api/health")
        print("5. Grafana Health:", r_grafana_health.status_code, r_grafana_health.json())

        r_datasources = client.get("http://localhost:3000/api/datasources", auth=("admin", "admin"))
        print("   Grafana Datasources:", [(ds["name"], ds["type"], ds["url"]) for ds in r_datasources.json()])

        # 6. Grafana Dashboards
        r_dashboards = client.get("http://localhost:3000/api/search", auth=("admin", "admin"))
        for d in r_dashboards.json():
            print(f"   Dashboard: '{d['title']}', uid={d.get('uid')}, url={d.get('url')}")

        # 7. Prometheus Series Verification
        print("\n7. Prometheus Scraped Series Verification:")
        for query in [
            "http_requests_total",
            "db_pool_timeouts_total",
            "db_pool_available_connections",
            "db_pool_checked_out_connections",
            "db_connection_wait_seconds_count",
            "inventory_request_duration_seconds_count"
        ]:
            r_q = client.get(f"http://localhost:9090/api/v1/query?query={query}")
            res = r_q.json()["data"]["result"]
            print(f"   Query '{query}': {len(res)} series active")
            if res:
                sample = res[0]
                print(f"     Sample value: {sample['value'][1]} (labels: {sample['metric']})")

        # 8. Alerting States
        r_alerts = client.get("http://localhost:9090/api/v1/alerts")
        alerts = r_alerts.json()["data"]["alerts"]
        print(f"\n8. Prometheus Active Alerts: {len(alerts)}")
        for a in alerts:
            aname = a["labels"].get("alertname", "unknown")
            state = a.get("state", "unknown")
            print(f"   Alert: {aname}, state: {state}")


if __name__ == "__main__":
    verify_all()

import httpx
import time

def send_traffic():
    with httpx.Client(base_url="http://localhost:8000", timeout=10.0) as client:
        print("--- Sending Normal Workload ---")
        created_ids = []
        for i in range(1, 6):
            r = client.post("/orders", json={"product_id": f"laptop-{i:03d}", "quantity": 1})
            order_id = r.json().get("id")
            created_ids.append(order_id)
            print(f"Normal Order {i}: status={r.status_code}, order_id={order_id}")
            time.sleep(0.1)

        for oid in created_ids[:3]:
            r_get = client.get(f"/orders/{oid}")
            print(f"GET /orders/{oid}: status={r_get.status_code}")

        r_unavail = client.post("/orders", json={"product_id": "out-of-stock-001", "quantity": 1})
        print(f"Unavailable product: status={r_unavail.status_code}")

        r_invalid = client.post("/orders", json={"product_id": "", "quantity": 1})
        print(f"Invalid product_id: status={r_invalid.status_code}")


if __name__ == "__main__":
    send_traffic()

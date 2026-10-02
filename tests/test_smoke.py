from app.config import Settings
from app.models import Order
from app.schemas import OrderCreate, OrderResponse


def test_settings_defaults():
    settings = Settings()
    assert settings.APP_NAME == "OrderFlow"
    assert settings.DB_POOL_SIZE == 5
    assert settings.DB_MAX_OVERFLOW == 0


def test_order_schema_validation():
    payload = OrderCreate(product_id="prod-123", quantity=2)
    assert payload.product_id == "prod-123"
    assert payload.quantity == 2


def test_order_model_mapping():
    order = Order(id=1, product_id="prod-123", quantity=2, status="PENDING")
    assert order.id == 1
    assert order.product_id == "prod-123"
    assert order.quantity == 2
    assert order.status == "PENDING"

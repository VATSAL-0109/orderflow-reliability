from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrderCreate(BaseModel):
    """Payload to create a new order."""

    product_id: str = Field(
        ..., min_length=1, max_length=64, description="Product identifier"
    )
    quantity: int = Field(..., gt=0, description="Quantity must be greater than zero")

    @field_validator("product_id")
    @classmethod
    def validate_product_id(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("product_id must not be empty or whitespace")
        return stripped


class OrderResponse(BaseModel):
    """Serialized order representation."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: str
    quantity: int
    status: str


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    service: str

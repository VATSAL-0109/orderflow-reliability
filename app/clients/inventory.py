import logging
import time
import httpx

from app.metrics import INVENTORY_REQUEST_DURATION_SECONDS

logger = logging.getLogger("orderflow.inventory_client")


class InventoryError(Exception):
    """Base exception for inventory client errors."""
    pass


class InventoryUnavailableError(InventoryError):
    """Raised when the product is out of stock / unavailable."""
    pass


class InventoryTimeoutError(InventoryError):
    """Raised when downstream inventory call times out."""
    pass


class InventoryDownstreamError(InventoryError):
    """Raised when downstream returns non-2xx status."""

    def __init__(self, status_code: int, message: str):
        super().__init__(
            f"Downstream inventory error (status {status_code}): {message}"
        )
        self.status_code = status_code


class InventoryClient:
    """HTTP client for communicating with the downstream inventory service."""

    def __init__(self, base_url: str, timeout_seconds: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def check_inventory(self, product_id: str) -> bool:
        """Check product availability.

        Raises:
            InventoryUnavailableError: Product is out of stock.
            InventoryTimeoutError: Downstream request timed out.
            InventoryDownstreamError: Downstream request returned non-2xx or connection error.

        Returns:
            True if available.
        """
        url = f"{self.base_url}/inventory/{product_id}"
        start_time = time.perf_counter()
        status_label = "error"

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(url)

            if response.status_code != 200:
                status_label = "error"
                logger.warning(
                    "Downstream inventory returned non-200",
                    extra={
                        "product_id": product_id,
                        "status_code": response.status_code,
                    },
                )
                raise InventoryDownstreamError(
                    status_code=response.status_code,
                    message=response.text,
                )

            data = response.json()
            is_available = bool(data.get("available", False))

            if not is_available:
                status_label = "unavailable"
                logger.info(
                    "Product is unavailable in inventory",
                    extra={"product_id": product_id},
                )
                raise InventoryUnavailableError(
                    f"Product '{product_id}' is unavailable in inventory"
                )

            status_label = "success"
            return True

        except httpx.TimeoutException as exc:
            status_label = "timeout"
            logger.error(
                "Downstream inventory request timed out",
                extra={
                    "product_id": product_id,
                    "timeout_seconds": self.timeout_seconds,
                },
            )
            raise InventoryTimeoutError(
                f"Inventory service timed out after {self.timeout_seconds}s"
            ) from exc

        except httpx.RequestError as exc:
            status_label = "error"
            logger.error(
                "Downstream inventory connection failure",
                extra={"product_id": product_id, "error": str(exc)},
            )
            raise InventoryDownstreamError(
                status_code=502,
                message=f"Connection failed: {str(exc)}",
            ) from exc

        finally:
            duration = time.perf_counter() - start_time
            INVENTORY_REQUEST_DURATION_SECONDS.labels(
                status=status_label
            ).observe(duration)

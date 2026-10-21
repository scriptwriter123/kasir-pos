import asyncio
from typing import Any

from app.core.config import settings
from app.payments.midtrans_gateway import (
    MidtransConfigurationError,
    MidtransGateway,
    MidtransProviderError,
)


class PaymentServiceError(RuntimeError):
    pass


class PaymentService:
    def __init__(self):
        self._gateway = MidtransGateway(
            settings.midtrans_server_key,
            notification_url=settings.midtrans_notification_url,
        )

    async def create_qris_payment(self, order_id: str, amount: int) -> dict[str, Any]:
        try:
            return await self._gateway.create_qris(order_id, amount)
        except MidtransConfigurationError as exc:
            raise PaymentServiceError(str(exc)) from exc
        except MidtransProviderError as exc:
            raise PaymentServiceError(str(exc)) from exc

    async def create_bank_transfer_payment(
        self,
        order_id: str,
        amount: int,
        bank: str | None = None,
    ) -> dict[str, Any]:
        try:
            return await self._gateway.create_bank_transfer(order_id, amount, bank)
        except MidtransConfigurationError as exc:
            raise PaymentServiceError(str(exc)) from exc
        except MidtransProviderError as exc:
            raise PaymentServiceError(str(exc)) from exc

    async def check_payment_status(self, order_id: str) -> dict[str, Any]:
        try:
            return await self._gateway.get_status(order_id)
        except MidtransConfigurationError as exc:
            raise PaymentServiceError(str(exc)) from exc
        except MidtransProviderError as exc:
            raise PaymentServiceError(str(exc)) from exc

    async def wait_for_payment(
        self,
        order_id: str,
        poll_interval: float = 3.0,
        timeout: float = 300.0,
    ) -> dict[str, Any]:
        elapsed = 0.0
        while elapsed < timeout:
            status = await self.check_payment_status(order_id)
            if status.get("paid"):
                return status
            if status.get("status") in ("failed", "cancelled", "expired"):
                return status
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        return {"status": "timeout", "paid": False, "order_id": order_id}

    def verify_webhook(self, notification: dict[str, Any]) -> bool:
        try:
            return self._gateway.verify_notification(notification)
        except MidtransConfigurationError:
            return False
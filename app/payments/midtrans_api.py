import re
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import settings
from app.payments.midtrans_gateway import (
    MidtransConfigurationError,
    MidtransGateway,
    MidtransProviderError,
)


ORDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,50}$")


class CreateQRISRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=50)
    amount: int = Field(gt=0)

    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("order_id")
    @classmethod
    def validate_order_id(cls, value: str) -> str:
        if not ORDER_ID_PATTERN.fullmatch(value):
            raise ValueError("Format order_id tidak valid.")
        return value


class MidtransNotification(BaseModel):
    order_id: str
    status_code: str
    gross_amount: str
    signature_key: str
    transaction_status: str
    fraud_status: str | None = None

    model_config = ConfigDict(extra="ignore")


class CreateBankTransferRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=50)
    amount: int = Field(gt=0)
    bank: str | None = Field(default=None, max_length=30)

    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("order_id")
    @classmethod
    def validate_order_id(cls, value: str) -> str:
        if not ORDER_ID_PATTERN.fullmatch(value):
            raise ValueError("Format order_id tidak valid.")
        return value

    @field_validator("bank")
    @classmethod
    def validate_bank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not re.fullmatch(r"^[A-Za-z0-9._-]{1,30}$", value):
            raise ValueError("Format bank tidak valid.")
        return value


def create_app(gateway: MidtransGateway | None = None) -> FastAPI:
    midtrans = gateway or MidtransGateway(
        settings.midtrans_server_key,
        notification_url=settings.midtrans_notification_url,
    )
    api = FastAPI(title="POS Midtrans QRIS Sandbox", version="0.1.0")

    @api.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "environment": "sandbox"}

    @api.post("/api/payments/qris")
    async def create_qris(payload: CreateQRISRequest) -> dict[str, Any]:
        if not ORDER_ID_PATTERN.fullmatch(payload.order_id):
            raise HTTPException(status_code=422, detail="Format order_id tidak valid.")
        try:
            return await midtrans.create_qris(payload.order_id, payload.amount)
        except MidtransConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except MidtransProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @api.post("/api/payments/bank-transfer")
    async def create_bank_transfer(payload: CreateBankTransferRequest) -> dict[str, Any]:
        if not ORDER_ID_PATTERN.fullmatch(payload.order_id):
            raise HTTPException(status_code=422, detail="Format order_id tidak valid.")
        try:
            return await midtrans.create_bank_transfer(
                payload.order_id, payload.amount, payload.bank
            )
        except MidtransConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except MidtransProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @api.get("/api/payments/{order_id}")
    async def payment_status(order_id: str) -> dict[str, Any]:
        if not ORDER_ID_PATTERN.fullmatch(order_id):
            raise HTTPException(status_code=422, detail="Format order_id tidak valid.")
        try:
            return await midtrans.get_status(order_id)
        except MidtransConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except MidtransProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @api.post("/api/webhooks/midtrans")
    async def midtrans_webhook(
        notification: MidtransNotification,
    ) -> dict[str, Any]:
        try:
            valid_signature = midtrans.verify_notification(
                notification.model_dump()
            )
        except MidtransConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if not valid_signature:
            raise HTTPException(status_code=401, detail="Signature Midtrans tidak valid.")
        return midtrans.notification_status(notification.model_dump())

    return api


app = create_app()

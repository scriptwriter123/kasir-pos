import re
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import settings
from app.payments.dana_gateway import (
    DanaConfigurationError,
    DanaGateway,
    DanaProviderError,
)


ORDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,50}$")


class CreateDanaQRISRequest(BaseModel):
    partner_reference_no: str = Field(min_length=1, max_length=25)
    amount: int = Field(gt=0)

    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("partner_reference_no")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        if not ORDER_ID_PATTERN.fullmatch(value):
            raise ValueError("Format partner_reference_no tidak valid.")
        return value


def create_app(gateway: DanaGateway | None = None) -> FastAPI:
    dana = gateway or DanaGateway(
        partner_id=settings.dana_partner_id,
        merchant_id=settings.dana_merchant_id,
        private_key=settings.dana_private_key,
        base_url=settings.dana_base_url,
    )
    api = FastAPI(title="POS DANA QRIS Acquirer Sandbox", version="0.1.0")

    @api.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "environment": "sandbox"}

    @api.post("/api/payments/dana-qris")
    async def create_dana_qris(payload: CreateDanaQRISRequest) -> dict[str, Any]:
        try:
            result = await dana.create_qris(
                payload.partner_reference_no, payload.amount
            )
        except DanaConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except DanaProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "partner_reference_no": payload.partner_reference_no,
            "amount": payload.amount,
            "qr_content": DanaGateway.qr_content(result),
            "response_code": result.get("responseCode"),
            "response_message": result.get("responseMessage"),
            "paid": DanaGateway.is_paid(result),
            "reference_no": result.get("referenceNo"),
        }

    @api.post("/api/payments/dana-qris/{partner_reference_no}/status")
    async def query_dana_qris(partner_reference_no: str) -> dict[str, Any]:
        if not ORDER_ID_PATTERN.fullmatch(partner_reference_no):
            raise HTTPException(status_code=422, detail="Format partner_reference_no tidak valid.")
        try:
            result = await dana.query_payment(partner_reference_no)
        except DanaConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except DanaProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "partner_reference_no": partner_reference_no,
            "response_code": result.get("responseCode"),
            "response_message": result.get("responseMessage"),
            "paid": DanaGateway.is_paid(result),
        }

    return api


app = create_app()
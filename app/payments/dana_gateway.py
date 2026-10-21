import base64
import hashlib
import json
from typing import Any
from urllib.parse import urlsplit

import httpx


DANA_SANDBOX_BASE_URL = "https://gateway-mp-sit.dana.id"


class DanaConfigurationError(RuntimeError):
    pass


class DanaProviderError(RuntimeError):
    pass


def _minify(body: str) -> str:
    data = json.loads(body)
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def _sha256_hex(body: str) -> str:
    return hashlib.sha256(_minify(body).encode("utf-8")).hexdigest()


def _sign_string(
    method: str,
    path: str,
    body: str,
    timestamp: str,
) -> str:
    digest = _sha256_hex(body)
    return f"{method.upper()}:{path}:{digest}:{timestamp}"


class DanaGateway:
    def __init__(
        self,
        partner_id: str | None,
        merchant_id: str | None,
        private_key: str | None,
        *,
        base_url: str = DANA_SANDBOX_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 15.0,
    ):
        self.partner_id = partner_id.strip() if partner_id else ""
        self.merchant_id = merchant_id.strip() if merchant_id else ""
        self.private_key = private_key.strip() if private_key else ""
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.timeout = timeout

    async def create_qris(
        self,
        partner_reference_no: str,
        amount: int,
        merchant_id: str | None = None,
        store_id: str | None = None,
        validity_period: str | None = None,
    ) -> dict[str, Any]:
        self._require_credentials()
        payload: dict[str, Any] = {
            "merchantId": merchant_id or self.merchant_id,
            "partnerReferenceNo": partner_reference_no,
            "amount": {"value": f"{amount:.2f}", "currency": "IDR"},
            "storeId": store_id or "",
            "additionalInfo": {
                "terminalSource": "MER",
                "envInfo": {
                    "terminalType": "SYSTEM",
                    "orderTerminalType": "APP",
                },
            },
        }
        if validity_period:
            payload["validityPeriod"] = validity_period

        return await self._request(
            "POST",
            "/v1.0/qr/qr-mpm-generate.htm",
            json=payload,
        )

    async def query_payment(
        self,
        partner_reference_no: str,
        service_code: str = "47",
        amount: int | None = None,
    ) -> dict[str, Any]:
        self._require_credentials()
        payload: dict[str, Any] = {
            "originalPartnerReferenceNo": partner_reference_no,
            "serviceCode": service_code,
            "additionalInfo": {},
        }
        if amount is not None:
            payload["amount"] = {"value": f"{amount:.2f}", "currency": "IDR"}

        return await self._request(
            "POST",
            "/rest/v1.1/debit/status",
            json=payload,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_credentials()
        body = json.dumps(json, separators=(",", ":"), ensure_ascii=False) if json else "{}"
        timestamp = self._timestamp()
        signature = self._signature(method, path, body, timestamp)
        headers = {
            "Content-Type": "application/json",
            "X-TIMESTAMP": timestamp,
            "X-SIGNATURE": signature,
            "X-PARTNER-ID": self.partner_id,
            "X-EXTERNAL-ID": self.partner_id,
            "CHANNEL-ID": "95221",
            "ORIGIN": self.base_url,
        }
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=self.timeout,
        ) as client:
            try:
                response = await client.request(
                    method, url, content=body.encode("utf-8"), headers=headers
                )
            except httpx.HTTPError as exc:
                raise DanaProviderError(
                    f"Tidak dapat menghubungi DANA: {exc}"
                ) from exc
        if response.is_error:
            try:
                message = response.json().get("responseMessage")
            except (ValueError, AttributeError):
                message = None
            raise DanaProviderError(
                f"DANA menolak permintaan: {message or f'HTTP {response.status_code}'}"
            )
        try:
            result = response.json()
        except ValueError as exc:
            raise DanaProviderError("Respons DANA bukan JSON yang valid.") from exc
        if not isinstance(result, dict):
            raise DanaProviderError("Format respons DANA tidak valid.")
        return result

    def _signature(self, method: str, path: str, body: str, timestamp: str) -> str:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        string_to_sign = _sign_string(method, path, body, timestamp)
        private_key = serialization.load_pem_private_key(
            self.private_key.encode("utf-8"),
            password=None,
        )
        signature = private_key.sign(
            string_to_sign.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("ascii")

    @staticmethod
    def _timestamp() -> str:
        from datetime import datetime, timezone, timedelta

        return (datetime.now(timezone.utc) + timedelta(hours=7)).strftime(
            "%Y-%m-%dT%H:%M:%S+07:00"
        )

    def _require_credentials(self) -> None:
        missing = [
            name
            for name, value in (
                ("DANA_PARTNER_ID", self.partner_id),
                ("DANA_MERCHANT_ID", self.merchant_id),
                ("DANA_PRIVATE_KEY", self.private_key),
            )
            if not value
        ]
        if missing:
            raise DanaConfigurationError(
                "Kredensial DANA belum lengkap: " + ", ".join(missing)
            )

    @staticmethod
    def is_paid(response: dict[str, Any]) -> bool:
        return (
            response.get("responseCode") == "2004700"
            or response.get("responseCode") == "00"
        )

    @staticmethod
    def qr_content(response: dict[str, Any]) -> str | None:
        return response.get("qrContent")

    @staticmethod
    def status_description(response: dict[str, Any]) -> str:
        return response.get("responseMessage", "")
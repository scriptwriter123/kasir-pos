import base64
import hashlib
import hmac
from typing import Any
from urllib.parse import urlsplit

import httpx


SANDBOX_API_URL = "https://api.sandbox.midtrans.com/v2"


class MidtransConfigurationError(RuntimeError):
    pass


class MidtransProviderError(RuntimeError):
    pass


class MidtransGateway:
    def __init__(
        self,
        server_key: str | None,
        notification_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 15.0,
    ):
        self.server_key = server_key.strip() if server_key else ""
        self.notification_url = notification_url
        self.transport = transport
        self.timeout = timeout

    async def create_qris(self, order_id: str, amount: int) -> dict[str, Any]:
        self._require_server_key()
        payload: dict[str, Any] = {
            "payment_type": "qris",
            "transaction_details": {
                "order_id": order_id,
                "gross_amount": amount,
            },
        }
        headers = {}
        if self.notification_url:
            headers["X-Override-Notification"] = self.notification_url

        charge = await self._request("POST", "/charge", json=payload, headers=headers)
        actions = charge.get("actions")
        qr_action = next(
            (
                action
                for action in actions or []
                if action.get("name") == "generate-qr-code"
                and action.get("method", "").upper() == "GET"
            ),
            None,
        )
        if not isinstance(qr_action, dict) or not qr_action.get("url"):
            raise MidtransProviderError(
                "Midtrans tidak mengembalikan URL gambar QRIS."
            )

        qr_url = qr_action["url"]
        parsed_url = urlsplit(qr_url)
        if (
            parsed_url.scheme != "https"
            or parsed_url.hostname != "api.sandbox.midtrans.com"
        ):
            raise MidtransProviderError(
                "URL gambar QRIS dari Midtrans tidak valid untuk sandbox."
            )

        image = await self._request_image(qr_url)
        return {
            "order_id": order_id,
            "amount": amount,
            "transaction_id": charge.get("transaction_id"),
            "transaction_status": charge.get("transaction_status", "pending"),
            "qr_image_base64": base64.b64encode(image.content).decode("ascii"),
            "qr_image_content_type": image.headers["content-type"].split(";")[0],
        }

    async def create_bank_transfer(
        self,
        order_id: str,
        amount: int,
        bank: str | None = None,
    ) -> dict[str, Any]:
        self._require_server_key()
        payload: dict[str, Any] = {
            "payment_type": "bank_transfer",
            "transaction_details": {
                "order_id": order_id,
                "gross_amount": amount,
            },
        }
        if bank:
            payload["bank_transfer"] = {"bank": bank}
        headers: dict[str, str] = {}
        if self.notification_url:
            headers["X-Override-Notification"] = self.notification_url

        charge = await self._request(
            "POST", "/charge", json=payload, headers=headers
        )
        return {
            "order_id": order_id,
            "amount": amount,
            "payment_type": "bank_transfer",
            "bank": bank,
            "transaction_id": charge.get("transaction_id"),
            "transaction_status": charge.get("transaction_status", "pending"),
            "status": self._normalized_status(
                charge.get("transaction_status", "pending"),
                charge.get("fraud_status"),
            ),
            "paid": charge.get("transaction_status") == "settlement"
            and charge.get("fraud_status") == "accept",
            "va_number": charge.get("va_numbers", [{}])[0].get("va_number")
            if charge.get("va_numbers")
            else None,
        }

    async def get_status(self, order_id: str) -> dict[str, Any]:
        self._require_server_key()
        result = await self._request("GET", f"/{order_id}/status")
        transaction_status = result.get("transaction_status", "unknown")
        fraud_status = result.get("fraud_status")
        return {
            "order_id": order_id,
            "transaction_id": result.get("transaction_id"),
            "transaction_status": transaction_status,
            "fraud_status": fraud_status,
            "status": self._normalized_status(transaction_status, fraud_status),
            "paid": transaction_status == "settlement" and fraud_status == "accept",
            "amount": result.get("gross_amount"),
        }

    def verify_notification(self, notification: dict[str, Any]) -> bool:
        self._require_server_key()
        order_id = notification.get("order_id")
        status_code = notification.get("status_code")
        gross_amount = notification.get("gross_amount")
        received_signature = notification.get("signature_key")
        if not all(
            isinstance(value, str) and value
            for value in (order_id, status_code, gross_amount, received_signature)
        ):
            return False
        signed_data = f"{order_id}{status_code}{gross_amount}{self.server_key}"
        expected_signature = hashlib.sha512(
            signed_data.encode("utf-8")
        ).hexdigest()
        return hmac.compare_digest(expected_signature, received_signature)

    @staticmethod
    def notification_status(notification: dict[str, Any]) -> dict[str, Any]:
        transaction_status = notification.get("transaction_status", "unknown")
        fraud_status = notification.get("fraud_status")
        return {
            "order_id": notification["order_id"],
            "transaction_status": transaction_status,
            "status": MidtransGateway._normalized_status(
                transaction_status,
                fraud_status,
            ),
            "paid": transaction_status == "settlement" and fraud_status == "accept",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=SANDBOX_API_URL,
            auth=(self.server_key, ""),
            timeout=self.timeout,
            transport=self.transport,
        ) as client:
            try:
                response = await client.request(method, path, json=json, headers=headers)
            except httpx.HTTPError as exc:
                raise MidtransProviderError(
                    f"Tidak dapat menghubungi Midtrans: {exc}"
                ) from exc
        if response.is_error:
            try:
                provider_message = response.json().get("status_message")
            except (ValueError, AttributeError):
                provider_message = None
            message = provider_message or f"HTTP {response.status_code}"
            raise MidtransProviderError(f"Midtrans menolak permintaan: {message}")
        try:
            result = response.json()
        except ValueError as exc:
            raise MidtransProviderError(
                "Respons Midtrans bukan JSON yang valid."
            ) from exc
        if not isinstance(result, dict):
            raise MidtransProviderError("Format respons Midtrans tidak valid.")
        return result

    async def _request_image(self, url: str) -> httpx.Response:
        async with httpx.AsyncClient(
            auth=(self.server_key, ""),
            timeout=self.timeout,
            transport=self.transport,
        ) as client:
            try:
                response = await client.get(url)
            except httpx.HTTPError as exc:
                raise MidtransProviderError(
                    f"Gagal mengambil gambar QRIS dari Midtrans: {exc}"
                ) from exc
        if response.is_error:
            raise MidtransProviderError(
                "Midtrans gagal mengirim gambar QRIS "
                f"(HTTP {response.status_code})."
            )
        if not response.headers.get("content-type", "").startswith("image/"):
            raise MidtransProviderError(
                "Respons gambar QRIS dari Midtrans bukan berkas gambar."
            )
        return response

    def _require_server_key(self) -> None:
        if not self.server_key:
            raise MidtransConfigurationError(
                "MIDTRANS_SERVER_KEY belum dikonfigurasi untuk sandbox."
            )

    @staticmethod
    def _normalized_status(transaction_status: str, fraud_status: str | None) -> str:
        if transaction_status == "settlement":
            return "paid" if fraud_status == "accept" else "review"
        return {
            "pending": "pending",
            "expire": "expired",
            "cancel": "cancelled",
            "deny": "failed",
            "failure": "failed",
        }.get(transaction_status, "unknown")

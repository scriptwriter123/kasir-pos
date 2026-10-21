import asyncio
import hashlib
import json

import httpx
import pytest

from app.payments.midtrans_api import create_app
from app.payments.midtrans_gateway import MidtransGateway


SERVER_KEY = "sandbox-test-server-key"
QR_URL = (
    "https://api.sandbox.midtrans.com/v2/qris/"
    "transaction-123/qr-code"
)


def request_api(app, method: str, path: str, json_body=None) -> httpx.Response:
    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.request(method, path, json=json_body)

    return asyncio.run(send_request())


@pytest.fixture
def gateway_transport():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v2/charge":
            return httpx.Response(
                201,
                json={
                    "transaction_id": "transaction-123",
                    "transaction_status": "pending",
                    "actions": [
                        {
                            "name": "generate-qr-code",
                            "method": "GET",
                            "url": QR_URL,
                        }
                    ],
                },
            )
        if request.url == httpx.URL(QR_URL):
            return httpx.Response(
                200,
                content=b"fake-png-image",
                headers={"content-type": "image/png"},
            )
        if request.url.path == "/v2/order-123/status":
            return httpx.Response(
                200,
                json={
                    "order_id": "order-123",
                    "transaction_id": "transaction-123",
                    "transaction_status": "settlement",
                    "fraud_status": "accept",
                    "gross_amount": "25000.00",
                },
            )
        return httpx.Response(404, json={"status_message": "Not found"})

    return httpx.MockTransport(handler), requests


def test_create_qris_returns_qr_image_and_sends_sandbox_charge(gateway_transport):
    transport, requests = gateway_transport
    response = request_api(
        create_app(MidtransGateway(SERVER_KEY, transport=transport)),
        "POST",
        "/api/payments/qris",
        {"order_id": "order-123", "amount": 25_000},
    )

    assert response.status_code == 200
    assert response.json()["order_id"] == "order-123"
    assert response.json()["transaction_status"] == "pending"
    assert response.json()["qr_image_content_type"] == "image/png"
    assert len(requests) == 2
    charge = requests[0]
    assert charge.url == httpx.URL("https://api.sandbox.midtrans.com/v2/charge")
    assert json.loads(charge.content) == {
        "payment_type": "qris",
        "transaction_details": {
            "order_id": "order-123",
            "gross_amount": 25_000,
        },
    }


def test_payment_status_is_confirmed_from_midtrans(gateway_transport):
    transport, _requests = gateway_transport
    response = request_api(
        create_app(MidtransGateway(SERVER_KEY, transport=transport)),
        "GET",
        "/api/payments/order-123",
    )

    assert response.status_code == 200
    assert response.json()["paid"] is True
    assert response.json()["status"] == "paid"
    assert response.json()["transaction_status"] == "settlement"


def test_settlement_is_not_paid_without_accepted_fraud_status():
    assert MidtransGateway.notification_status(
        {
            "order_id": "order-123",
            "transaction_status": "settlement",
            "fraud_status": "challenge",
        }
    ) == {
        "order_id": "order-123",
        "transaction_status": "settlement",
        "status": "review",
        "paid": False,
    }


def test_webhook_accepts_valid_signature_and_rejects_invalid_signature():
    signed_values = {
        "order_id": "order-123",
        "status_code": "200",
        "gross_amount": "25000.00",
    }
    signature = hashlib.sha512(
        (
            signed_values["order_id"]
            + signed_values["status_code"]
            + signed_values["gross_amount"]
            + SERVER_KEY
        ).encode("utf-8")
    ).hexdigest()
    notification = {
        **signed_values,
        "signature_key": signature,
        "transaction_status": "settlement",
        "fraud_status": "accept",
    }
    api = create_app(MidtransGateway(SERVER_KEY))

    accepted = request_api(api, "POST", "/api/webhooks/midtrans", notification)
    notification["signature_key"] = "invalid"
    rejected = request_api(api, "POST", "/api/webhooks/midtrans", notification)

    assert accepted.status_code == 200
    assert accepted.json()["paid"] is True
    assert rejected.status_code == 401


def test_missing_server_key_fails_explicitly():
    response = request_api(
        create_app(MidtransGateway(None)),
        "POST",
        "/api/payments/qris",
        {"order_id": "order-123", "amount": 25_000},
    )

    assert response.status_code == 503
    assert "MIDTRANS_SERVER_KEY" in response.json()["detail"]


@pytest.mark.parametrize(
    "payload",
    [
        {"order_id": "bad order id", "amount": 1_000},
        {"order_id": "order-123", "amount": 0},
        {"order_id": "order-123", "amount": 1.5},
    ],
)
def test_charge_rejects_invalid_order_or_amount(payload):
    response = request_api(
        create_app(MidtransGateway(SERVER_KEY)),
        "POST",
        "/api/payments/qris",
        payload,
    )

    assert response.status_code == 422


def test_charge_rejects_qr_url_outside_midtrans_sandbox():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={
                "actions": [
                    {
                        "name": "generate-qr-code",
                        "method": "GET",
                        "url": "https://attacker.example/qr",
                    }
                ]
            },
        )

    api = create_app(
        MidtransGateway(SERVER_KEY, transport=httpx.MockTransport(handler))
    )

    response = request_api(
        api,
        "POST",
        "/api/payments/qris",
        {"order_id": "order-123", "amount": 25_000},
    )

    assert response.status_code == 502
    assert "URL gambar QRIS" in response.json()["detail"]


@pytest.fixture
def bank_transfer_transport():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v2/charge":
            body = json.loads(request.content)
            if body.get("payment_type") == "bank_transfer":
                return httpx.Response(
                    201,
                    json={
                        "transaction_id": "transaction-456",
                        "transaction_status": "pending",
                        "va_numbers": [
                            {"bank": body.get("bank_transfer", {}).get("bank", "bca"),
                             "va_number": "1234567890"}
                        ],
                    },
                )
            return httpx.Response(404, json={"status_message": "Not found"})
        return httpx.Response(404, json={"status_message": "Not found"})

    return httpx.MockTransport(handler), requests


def test_create_bank_transfer_returns_va_number_and_sends_payload(bank_transfer_transport):
    transport, requests = bank_transfer_transport
    response = request_api(
        create_app(MidtransGateway(SERVER_KEY, transport=transport)),
        "POST",
        "/api/payments/bank-transfer",
        {"order_id": "order-456", "amount": 50_000, "bank": "bca"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["order_id"] == "order-456"
    assert data["payment_type"] == "bank_transfer"
    assert data["bank"] == "bca"
    assert data["transaction_id"] == "transaction-456"
    assert data["va_number"] == "1234567890"
    assert len(requests) == 1
    charge = requests[0]
    assert charge.url == httpx.URL("https://api.sandbox.midtrans.com/v2/charge")
    assert json.loads(charge.content) == {
        "payment_type": "bank_transfer",
        "transaction_details": {"order_id": "order-456", "gross_amount": 50_000},
        "bank_transfer": {"bank": "bca"},
    }


def test_create_bank_transfer_without_bank_omits_bank_transfer(bank_transfer_transport):
    transport, _requests = bank_transfer_transport
    response = request_api(
        create_app(MidtransGateway(SERVER_KEY, transport=transport)),
        "POST",
        "/api/payments/bank-transfer",
        {"order_id": "order-789", "amount": 75_000},
    )

    assert response.status_code == 200
    assert response.json()["bank"] is None


def test_bank_transfer_missing_server_key_fails_explicitly():
    response = request_api(
        create_app(MidtransGateway(None)),
        "POST",
        "/api/payments/bank-transfer",
        {"order_id": "order-123", "amount": 25_000},
    )

    assert response.status_code == 503
    assert "MIDTRANS_SERVER_KEY" in response.json()["detail"]


@pytest.mark.parametrize(
    "payload",
    [
        {"order_id": "bad order id", "amount": 1_000},
        {"order_id": "order-123", "amount": 0},
        {"order_id": "order-123", "amount": 1.5},
        {"order_id": "order-123", "amount": 1_000, "bank": "bad bank!"},
    ],
)
def test_bank_transfer_rejects_invalid_payload(payload):
    response = request_api(
        create_app(MidtransGateway(SERVER_KEY)),
        "POST",
        "/api/payments/bank-transfer",
        payload,
    )

    assert response.status_code == 422


def test_bank_transfer_provider_error_returns_502():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"status_message": "Invalid bank transfer payload"},
        )

    api = create_app(
        MidtransGateway(SERVER_KEY, transport=httpx.MockTransport(handler))
    )
    response = request_api(
        api,
        "POST",
        "/api/payments/bank-transfer",
        {"order_id": "order-123", "amount": 25_000, "bank": "bca"},
    )

    assert response.status_code == 502
    assert "Midtrans menolak permintaan" in response.json()["detail"]


def test_bank_transfer_settlement_marks_paid():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={
                "transaction_id": "transaction-999",
                "transaction_status": "settlement",
                "fraud_status": "accept",
                "va_numbers": [{"bank": "bca", "va_number": "9876543210"}],
            },
        )

    api = create_app(
        MidtransGateway(SERVER_KEY, transport=httpx.MockTransport(handler))
    )
    response = request_api(
        api,
        "POST",
        "/api/payments/bank-transfer",
        {"order_id": "order-999", "amount": 100_000, "bank": "bca"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["paid"] is True
    assert data["status"] == "paid"

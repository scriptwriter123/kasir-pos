import logging
from typing import Any

import httpx

from server.app.config import Settings

logger = logging.getLogger(__name__)


class MidtransSnapError(Exception):
    pass


def create_snap_transaction(
    settings: Settings,
    *,
    order_code: str,
    amount_idr: int,
    customer_name: str,
    customer_email: str,
    item_name: str,
) -> dict[str, Any]:
    """Buat transaksi Midtrans Snap, kembalikan token & redirect_url."""
    if not settings.midtrans_server_key:
        raise MidtransSnapError("MIDTRANS_SERVER_KEY belum dikonfigurasi.")

    payload = {
        "transaction_details": {
            "order_id": order_code,
            "gross_amount": amount_idr,
        },
        "customer_details": {
            "first_name": customer_name,
            "email": customer_email,
        },
        "item_details": [
            {
                "id": "plan",
                "price": amount_idr,
                "quantity": 1,
                "name": item_name,
            }
        ],
        "expiry": {"unit": "hours", "duration": 24},
    }

    url = f"{settings.midtrans_snap_api_url}/transactions"
    auth = (settings.midtrans_server_key, "")

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload, auth=auth)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:200]
        logger.error("Midtrans Snap HTTP %s: %s", exc.response.status_code, detail)
        raise MidtransSnapError(
            f"Midtrans menolak ({exc.response.status_code}): {detail}"
        ) from exc
    except httpx.RequestError as exc:
        logger.error("Midtrans Snap request error: %s", exc)
        raise MidtransSnapError(f"Gagal terhubung ke Midtrans: {exc}") from exc

    token = data.get("token")
    redirect_url = data.get("redirect_url")
    if not token:
        raise MidtransSnapError("Midtrans tidak mengembalikan token.")

    return {
        "token": token,
        "redirect_url": redirect_url,
        "raw": data,
    }

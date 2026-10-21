import hashlib
import hmac
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.app.config import Settings
from server.app.models import License, Order, Payment
from server.app.services.license_service import activate_license


class PaymentError(ValueError):
    pass


PAID_STATUSES = {"settlement", "capture"}
FAILED_STATUSES = {"deny", "cancel", "failure", "expire"}

# Simulasi ATM/transfer manual: VA deterministik per order, konfirmasi
# oleh customer lewat tombol "Saya Sudah Bayar" di halaman order.
SIMULATED_VA_PREFIX = "9876"
SIMULATED_ATM_PROVIDER = "atm-simulasi"


def simulated_va_number(order_code: str) -> str:
    """Nomor Virtual Account 16 digit yang stabil untuk satu order."""
    digest = hashlib.sha256(f"atm-simulasi:{order_code}".encode("utf-8")).hexdigest()
    tail = str(int(digest[:12], 16))[-12:].zfill(12)
    return SIMULATED_VA_PREFIX + tail


def format_va_display(va_number: str) -> str:
    return " ".join(
        va_number[index : index + 4]
        for index in range(0, len(va_number), 4)
    )


def simulate_atm_payment(
    session: Session,
    settings: Settings,
    order: Order,
) -> dict[str, Any]:
    """Tandai order lunas setelah customer mengonfirmasi transfer ATM.

    Meniru hasil akhir notifikasi gateway: baris ``Payment`` tercatat
    (idempoten via ``gateway_event_id``), order menjadi ``paid``, dan
    lisensi ditandatangani server. Dipanggil dari tombol
    "Saya Sudah Bayar" pada halaman order.
    """
    if order.status == "paid":
        return {"status": "paid", "order_status": "paid"}
    if order.status != "pending":
        raise PaymentError("Order ini tidak menunggu pembayaran.")

    event_id = f"{order.order_code}:{SIMULATED_ATM_PROVIDER}:settlement"
    existing = session.scalar(
        select(Payment).where(Payment.gateway_event_id == event_id)
    )
    if existing is None:
        session.add(
            Payment(
                order_id=order.id,
                license_id=order.license_id,
                provider=SIMULATED_ATM_PROVIDER,
                gateway_event_id=event_id,
                order_code=order.order_code,
                amount_idr=order.amount_idr,
                status="settlement",
                raw_notification=json.dumps(
                    {
                        "simulasi": True,
                        "provider": SIMULATED_ATM_PROVIDER,
                        "va_number": simulated_va_number(order.order_code),
                        "confirmed_at": datetime.now(timezone.utc).isoformat(),
                    },
                    ensure_ascii=False,
                ),
            )
        )
        session.flush()

    order.status = "paid"
    order.paid_at = datetime.now(timezone.utc)
    if order.license_id is not None:
        license_record = session.get(License, order.license_id)
        if license_record is not None:
            activate_license(session, license_record, settings)
    session.commit()
    return {"status": "paid", "order_status": "paid"}


def verify_midtrans_signature(
    notification: dict[str, Any],
    server_key: str,
) -> bool:
    order_id = notification.get("order_id")
    status_code = notification.get("status_code")
    gross_amount = notification.get("gross_amount")
    received = notification.get("signature_key")
    if not all(
        isinstance(value, str) and value
        for value in (order_id, status_code, gross_amount, received)
    ):
        return False
    expected = hashlib.sha512(
        f"{order_id}{status_code}{gross_amount}{server_key}".encode("utf-8")
    ).hexdigest()
    return hmac.compare_digest(expected, received)


def apply_midtrans_notification(
    session: Session,
    settings: Settings,
    notification: dict[str, Any],
) -> dict[str, Any]:
    """Webhook entry point: verify signature then process idempotently."""
    if not settings.midtrans_server_key:
        raise PaymentError("MIDTRANS_SERVER_KEY belum dikonfigurasi.")
    if not verify_midtrans_signature(notification, settings.midtrans_server_key):
        raise PaymentError("Signature Midtrans tidak valid.")
    return _apply_transaction(
        session,
        settings,
        order_code=str(notification.get("order_id", "")),
        transaction_status=str(notification.get("transaction_status", "unknown")),
        transaction_id=str(
            notification.get("transaction_id")
            or notification.get("status_code")
            or ""
        ),
        gross_amount=notification.get("gross_amount"),
        fraud_status=notification.get("fraud_status"),
        raw=notification,
    )


def apply_midtrans_status_result(
    session: Session,
    settings: Settings,
    status_result: dict[str, Any],
) -> dict[str, Any]:
    """Process a status query result obtained directly from Midtrans API."""
    return _apply_transaction(
        session,
        settings,
        order_code=str(status_result.get("order_id", "")),
        transaction_status=str(status_result.get("transaction_status", "unknown")),
        transaction_id=str(status_result.get("transaction_id") or ""),
        gross_amount=status_result.get("gross_amount"),
        fraud_status=status_result.get("fraud_status"),
        raw=status_result,
    )


def _apply_transaction(
    session: Session,
    settings: Settings,
    *,
    order_code: str,
    transaction_status: str,
    transaction_id: str,
    gross_amount: Any,
    fraud_status: str | None,
    raw: dict[str, Any],
) -> dict[str, Any]:
    order = session.scalar(select(Order).where(Order.order_code == order_code))
    if order is None:
        raise PaymentError("Order tidak ditemukan untuk notifikasi ini.")

    if str(gross_amount or ""):
        try:
            amounts_match = Decimal(str(gross_amount)) == Decimal(order.amount_idr)
        except InvalidOperation as exc:
            raise PaymentError("Nominal notifikasi tidak valid.") from exc
        if not amounts_match:
            raise PaymentError("Nominal notifikasi tidak cocok dengan order.")

    event_id = f"{order_code}:{transaction_id}:{transaction_status}"
    existing = session.scalar(
        select(Payment).where(Payment.gateway_event_id == event_id)
    )
    if existing is not None:
        return {"status": "duplicate", "order_status": order.status}

    try:
        session.add(
            Payment(
                order_id=order.id,
                license_id=order.license_id,
                provider="midtrans",
                gateway_event_id=event_id,
                order_code=order.order_code,
                amount_idr=order.amount_idr,
                status=transaction_status,
                raw_notification=json.dumps(raw, ensure_ascii=False),
            )
        )
        session.flush()
    except IntegrityError:
        session.rollback()
        return {"status": "duplicate", "order_status": order.status}

    if transaction_status in PAID_STATUSES:
        if transaction_status == "capture" and fraud_status not in (None, "accept"):
            session.commit()
            return {"status": "ignored", "order_status": order.status}
        if order.status != "paid":
            order.status = "paid"
            order.paid_at = datetime.now(timezone.utc)
            if order.license_id is not None:
                license_record = session.get(License, order.license_id)
                if license_record is not None:
                    activate_license(session, license_record, settings)
        session.commit()
        return {"status": "paid", "order_status": order.status}

    if transaction_status in FAILED_STATUSES:
        if order.status == "pending":
            order.status = "failed"
        session.commit()
        return {"status": "failed", "order_status": order.status}

    session.commit()
    return {"status": "pending", "order_status": order.status}

import json
import logging
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.app.licensing import (
    PRODUCT_NAME,
    LICENSE_SCHEMA_VERSION,
    SigningError,
    build_payload,
    load_private_key,
    sign_payload,
)
from server.app.models import Customer, Device, License, Order, Plan
from server.app.config import Settings
from server.app.security import hash_token, new_session_token
from server.app.services.midtrans_snap import MidtransSnapError, create_snap_transaction

DEVICE_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")

logger = logging.getLogger(__name__)

# Throttle verifikasi pembayaran saat POS polling (kunci: id order).
_LAST_VERIFY: dict[int, float] = {}
VERIFY_MIN_INTERVAL_SECONDS = 8.0
_VERIFY_MAX_ENTRIES = 2048


class LicenseServiceError(ValueError):
    pass


def parse_posreq(content: str) -> dict[str, Any]:
    try:
        request = json.loads(content)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise LicenseServiceError("File permintaan lisensi tidak dapat dibaca.") from exc
    if not isinstance(request, dict):
        raise LicenseServiceError("Isi file permintaan lisensi tidak valid.")
    if request.get("schema_version") != LICENSE_SCHEMA_VERSION:
        raise LicenseServiceError("Versi permintaan lisensi tidak didukung.")
    if request.get("product") != PRODUCT_NAME:
        raise LicenseServiceError("Permintaan ini bukan untuk POS Retail.")
    try:
        installation_id = str(uuid.UUID(str(request["installation_id"])))
    except (KeyError, TypeError, ValueError) as exc:
        raise LicenseServiceError("ID instalasi pada permintaan tidak valid.") from exc
    device_id = request.get("device_id")
    if not isinstance(device_id, str) or not DEVICE_ID_PATTERN.fullmatch(device_id):
        raise LicenseServiceError("ID komputer pada permintaan tidak valid.")
    store_name = str(request.get("store_name", "")).strip()
    if not store_name or len(store_name) > 150:
        raise LicenseServiceError("Nama toko pada permintaan tidak valid.")
    return {
        "installation_id": installation_id,
        "device_id": device_id,
        "store_name": store_name,
    }


def register_device(
    session: Session,
    customer: Customer,
    posreq_content: str,
) -> Device:
    parsed = parse_posreq(posreq_content)
    device = session.scalar(
        select(Device).where(
            Device.installation_id == parsed["installation_id"],
            Device.device_id == parsed["device_id"],
        )
    )
    if device is None:
        device = Device(
            customer_id=customer.id,
            installation_id=parsed["installation_id"],
            device_id=parsed["device_id"],
            store_name=parsed["store_name"],
        )
        session.add(device)
    else:
        if device.customer_id != customer.id:
            raise LicenseServiceError(
                "Instalasi ini terdaftar pada akun lain. Hubungi dukungan."
            )
        device.store_name = parsed["store_name"]
        device.is_active = True
    session.commit()
    return device


def issue_device_token(session: Session, device: Device) -> str:
    """Buat token perangkat untuk POS (auto-aktivasi). Simpan hash-nya."""
    token = new_session_token()
    device.token_hash = hash_token(token)
    session.commit()
    return token


def device_for_token(session: Session, token: str | None) -> Device | None:
    if not token:
        return None
    device = session.scalar(
        select(Device).where(Device.token_hash == hash_token(token))
    )
    if device is None or not device.is_active:
        return None
    return device


def license_for_installation(
    session: Session, installation_id: str, device_id: str
) -> License | None:
    license_record = session.scalar(
        select(License).where(
            License.installation_id == installation_id,
            License.device_id == device_id,
        )
    )
    if license_record is None:
        return None
    if license_record.status == "active" and _is_expired(license_record):
        return None
    return license_record


def active_license_document_for_device(
    session: Session, device: Device
) -> dict[str, Any] | None:
    """Dokumen .poslic bila lisensi sudah aktif; None bila belum/belum bayar."""
    license_record = license_for_installation(
        session, device.installation_id, device.device_id
    )
    if (
        license_record is None
        or license_record.status != "active"
        or license_record.payload_json is None
        or license_record.signature is None
    ):
        return None
    return license_document(license_record)


def get_plan(session: Session, plan_code: str) -> Plan:
    plan = session.scalar(select(Plan).where(Plan.code == plan_code))
    if plan is None:
        raise LicenseServiceError("Paket langganan tidak ditemukan.")
    return plan


def get_device(session: Session, customer: Customer, device_pk: int) -> Device:
    device = session.scalar(
        select(Device).where(Device.id == device_pk, Device.customer_id == customer.id)
    )
    if device is None:
        raise LicenseServiceError("Perangkat tidak ditemukan.")
    if not device.is_active:
        raise LicenseServiceError("Perangkat tidak aktif.")
    return device


def active_license_for_device(session: Session, device: Device) -> License | None:
    license_record = session.scalar(
        select(License).where(
            License.installation_id == device.installation_id,
            License.device_id == device.device_id,
        )
    )
    if license_record is None or license_record.status not in {"active", "pending"}:
        return None
    if license_record.status == "active" and _is_expired(license_record):
        return None
    return license_record


def create_checkout(
    session: Session,
    customer: Customer,
    *,
    device_pk: int,
    plan_code: str,
    settings: Settings | None = None,
) -> tuple[Order, License]:
    device = get_device(session, customer, device_pk)
    plan = get_plan(session, plan_code)

    license_record = session.scalar(
        select(License).where(
            License.installation_id == device.installation_id,
            License.device_id == device.device_id,
        )
    )
    if license_record is None:
        license_record = License(
            customer_id=customer.id,
            device_pk=device.id,
            license_id=secrets.token_hex(16).upper(),
            installation_id=device.installation_id,
            device_id=device.device_id,
            store_name=device.store_name,
            plan_code=plan.code,
            status="pending",
        )
        session.add(license_record)
        session.flush()
    else:
        license_record.plan_code = plan.code
        license_record.store_name = device.store_name

    existing_pending = session.scalar(
        select(Order).where(
            Order.license_id == license_record.id,
            Order.status == "pending",
        )
    )
    if existing_pending is not None:
        existing_pending.plan_code = plan.code
        existing_pending.amount_idr = plan.price_idr
        session.commit()
        # Belum ada snap token → buat sekarang.
        if settings is not None and existing_pending.snap_token is None:
            _attach_snap_token(session, settings, existing_pending, customer, plan)
        return existing_pending, license_record

    order = Order(
        order_code=f"POS-{secrets.token_hex(6).upper()}",
        customer_id=customer.id,
        license_id=license_record.id,
        plan_code=plan.code,
        amount_idr=plan.price_idr,
    )
    session.add(order)
    session.commit()

    if settings is not None:
        _attach_snap_token(session, settings, order, customer, plan)

    return order, license_record


def _attach_snap_token(
    session: Session,
    settings: Settings,
    order: Order,
    customer: Customer,
    plan: Plan,
) -> None:
    """Panggil Midtrans Snap & simpan token. Gagal → biarkan (order tetap ada)."""
    try:
        result = create_snap_transaction(
            settings,
            order_code=order.order_code,
            amount_idr=order.amount_idr,
            customer_name=customer.store_name or customer.email.split("@")[0],
            customer_email=customer.email,
            item_name=f"Lisensi {plan.name}",
        )
        order.snap_token = result["token"]
        session.commit()
    except MidtransSnapError:
        # Log tapi jangan gagalkan checkout — user tetap bisa "Cek Status" nanti.
        import logging

        logging.getLogger(__name__).warning(
            "Gagal membuat Snap token untuk order %s", order.order_code
        )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _is_expired(license_record: License) -> bool:
    if license_record.expires_at is None:
        return False
    return _as_utc(license_record.expires_at) <= datetime.now(timezone.utc)


def license_effective_status(license_record: License) -> str:
    if license_record.status == "pending":
        return "pending"
    if license_record.status != "active":
        return license_record.status
    return "expired" if _is_expired(license_record) else "active"


def plan_cycle(plan: Plan) -> str:
    """Siklus penagihan paket: bulanan / tahunan / selamanya / lainnya."""
    if plan.duration_days is None:
        return "lifetime"
    if plan.duration_days <= 45:
        return "monthly"
    if plan.duration_days <= 400:
        return "yearly"
    return "custom"


def cycle_from_code(plan_code: str) -> str:
    code = (plan_code or "").strip().lower()
    if code == "monthly":
        return "monthly"
    if code == "yearly":
        return "yearly"
    if code == "lifetime":
        return "lifetime"
    return "custom"


def plan_catalog(session: Session) -> list[dict[str, Any]]:
    """Daftar paket langganan aktif (bulanan, tahunan, selamanya)."""
    plans = session.scalars(
        select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.price_idr)
    ).all()
    return [
        {
            "code": plan.code,
            "name": plan.name,
            "cycle": plan_cycle(plan),
            "duration_days": plan.duration_days,
            "price_idr": plan.price_idr,
        }
        for plan in plans
    ]


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _as_utc(value).isoformat()


def remaining_time(expires_at: datetime | None) -> dict[str, Any]:
    """Sisa waktu langganan dalam detik, hari, dan teks siap tampil."""
    if expires_at is None:
        return {
            "seconds": None,
            "days": None,
            "text": "Berlaku selamanya",
            "expired": False,
        }
    delta = _as_utc(expires_at) - datetime.now(timezone.utc)
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        return {"seconds": 0, "days": 0, "text": "Masa berlaku berakhir", "expired": True}
    days = ceil(seconds / 86400)
    if days >= 1:
        text = f"Sisa {days} hari"
    else:
        hours = max(1, ceil(seconds / 3600))
        text = f"Sisa {hours} jam"
    return {"seconds": seconds, "days": days, "text": text, "expired": False}


def subscription_for_device(
    session: Session, device: Device
) -> dict[str, Any] | None:
    """Status langganan perangkat untuk kartu info POS; None bila belum ada."""
    license_record = license_for_installation(
        session, device.installation_id, device.device_id
    )
    if license_record is None:
        return None
    plan = session.scalar(select(Plan).where(Plan.code == license_record.plan_code))
    remaining = remaining_time(license_record.expires_at)
    return {
        "status": license_effective_status(license_record),
        "activated": license_effective_status(license_record) == "active",
        "license_id": license_record.license_id,
        "store_name": license_record.store_name,
        "plan": {
            "code": license_record.plan_code,
            "name": plan.name if plan else license_record.plan_code,
            "cycle": plan_cycle(plan) if plan else cycle_from_code(license_record.plan_code),
            "starts_at": _iso(license_record.starts_at),
            "expires_at": _iso(license_record.expires_at),
            "remaining_seconds": remaining["seconds"],
            "remaining_days": remaining["days"],
            "remaining_text": remaining["text"],
        },
        "plans": plan_catalog(session),
    }


def activate_license(
    session: Session,
    license_record: License,
    settings: Settings,
) -> dict[str, Any]:
    """Sign and persist the license document after a successful payment."""
    plan = get_plan(session, license_record.plan_code)
    now = datetime.now(timezone.utc)

    if plan.duration_days is None:
        starts_at = now
        expires_at = None
    elif license_record.status == "active" and license_record.expires_at is not None:
        current_expiry = _as_utc(license_record.expires_at)
        if current_expiry > now:
            starts_at = current_expiry
        else:
            starts_at = now
        expires_at = starts_at + timedelta(days=plan.duration_days)
    else:
        starts_at = now
        expires_at = now + timedelta(days=plan.duration_days)

    private_key = load_private_key(
        settings.license_private_key_path,
        settings.license_private_key_passphrase,
    )
    payload = build_payload(
        store_name=license_record.store_name,
        installation_id=license_record.installation_id,
        device_id=license_record.device_id,
        expires_at=expires_at,
        license_id=license_record.license_id,
        issued_at=now,
    )
    document = sign_payload(payload, private_key)

    license_record.starts_at = starts_at
    license_record.expires_at = expires_at
    license_record.status = "active"
    license_record.payload_json = json.dumps(
        document["payload"], ensure_ascii=False, sort_keys=True
    )
    license_record.signature = document["signature"]
    session.commit()
    return document


def license_document(license_record: License) -> dict[str, Any]:
    if license_record.payload_json is None or license_record.signature is None:
        raise LicenseServiceError("Lisensi belum diterbitkan.")
    payload = json.loads(license_record.payload_json)
    return {"payload": payload, "signature": license_record.signature}


def deactivate_license(session: Session, customer: Customer, license_pk: int) -> None:
    license_record = session.scalar(
        select(License).where(
            License.id == license_pk, License.customer_id == customer.id
        )
    )
    if license_record is None:
        raise LicenseServiceError("Lisensi tidak ditemukan.")
    license_record.status = "revoked"
    session.commit()


def list_licenses(session: Session, customer: Customer) -> list[License]:
    return list(
        session.scalars(
            select(License)
            .where(License.customer_id == customer.id)
            .order_by(License.created_at.desc())
        )
    )


def list_devices(session: Session, customer: Customer) -> list[Device]:
    return list(
        session.scalars(
            select(Device)
            .where(Device.customer_id == customer.id)
            .order_by(Device.created_at.desc())
        )
    )


def list_orders(session: Session, customer: Customer) -> list[Order]:
    return list(
        session.scalars(
            select(Order)
            .where(Order.customer_id == customer.id)
            .order_by(Order.created_at.desc())
        )
    )


def get_order(
    session: Session, customer: Customer, order_code: str
) -> Order | None:
    return session.scalar(
        select(Order).where(
            Order.order_code == order_code,
            Order.customer_id == customer.id,
        )
    )


def create_renewal(
    session: Session,
    customer: Customer,
    *,
    license_pk: int,
    plan_code: str,
) -> Order:
    license_record = session.scalar(
        select(License).where(
            License.id == license_pk, License.customer_id == customer.id
        )
    )
    if license_record is None:
        raise LicenseServiceError("Lisensi tidak ditemukan.")
    if license_record.status == "revoked":
        raise LicenseServiceError("Lisensi sudah dinonaktifkan.")
    plan = get_plan(session, plan_code)
    license_record.plan_code = plan.code

    existing_pending = session.scalar(
        select(Order).where(
            Order.license_id == license_record.id,
            Order.status == "pending",
        )
    )
    if existing_pending is not None:
        existing_pending.plan_code = plan.code
        existing_pending.amount_idr = plan.price_idr
        session.commit()
        return existing_pending

    order = Order(
        order_code=f"POS-{secrets.token_hex(6).upper()}",
        customer_id=customer.id,
        license_id=license_record.id,
        plan_code=plan.code,
        amount_idr=plan.price_idr,
    )
    session.add(order)
    session.commit()
    return order


def get_license_document(
    session: Session, customer: Customer, license_pk: int
) -> dict[str, Any]:
    license_record = session.scalar(
        select(License).where(
            License.id == license_pk, License.customer_id == customer.id
        )
    )
    if license_record is None:
        raise LicenseServiceError("Lisensi tidak ditemukan.")
    if license_effective_status(license_record) == "pending":
        raise LicenseServiceError(
            "Lisensi belum aktif. Selesaikan pembayaran terlebih dahulu."
        )
    return license_document(license_record)


def force_pay(
    session: Session,
    settings: Settings,
    order: Order,
) -> License:
    """Development helper: mark an order paid without a gateway event."""
    order.status = "paid"
    order.paid_at = datetime.now(timezone.utc)
    if order.license_id is None:
        raise LicenseServiceError("Order tidak terhubung ke lisensi.")
    license_record = session.get(License, order.license_id)
    if license_record is None:
        raise LicenseServiceError("Lisensi untuk order ini tidak ditemukan.")
    activate_license(session, license_record, settings)
    return license_record


def refresh_order_status(
    session: Session,
    settings: Settings,
    order: Order,
) -> dict[str, Any]:
    """Poll Midtrans for the latest transaction status of a pending order."""
    if order.status != "pending":
        return {"status": order.status}
    if not settings.midtrans_server_key:
        raise LicenseServiceError(
            "Pembayaran gateway belum dikonfigurasi pada server."
        )

    import httpx

    from server.app.services.payment_service import apply_midtrans_status_result

    try:
        response = httpx.get(
            f"{settings.midtrans_api_url}/{order.order_code}/status",
            auth=(settings.midtrans_server_key, ""),
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        raise LicenseServiceError(
            "Tidak dapat menghubungi gateway pembayaran."
        ) from exc
    if response.is_error:
        raise LicenseServiceError(
            "Gateway pembayaran tidak mengenali order ini."
        )
    try:
        result = response.json()
    except ValueError as exc:
        raise LicenseServiceError("Respons gateway tidak valid.") from exc
    return apply_midtrans_status_result(session, settings, result)


def _prune_verify_cache() -> None:
    if len(_LAST_VERIFY) <= _VERIFY_MAX_ENTRIES:
        return
    cutoff = time.monotonic() - 3600.0
    for order_pk in [
        key for key, stamp in _LAST_VERIFY.items() if stamp < cutoff
    ]:
        _LAST_VERIFY.pop(order_pk, None)


def verify_pending_for_device(
    session: Session,
    settings: Settings,
    device: Device,
) -> License | None:
    """Verifikasi pembayaran ke gateway saat POS polling.

    Pengganti webhook untuk lingkungan tanpa URL publik: ketika POS
    memanggil ``GET /api/pos/license`` sementara lisensinya masih
    ``pending``, server ikut menanyakan status transaksi ke Midtrans
    sehingga lisensi bisa diterbitkan begitu pembayaran lunas.

    Dibatasi per order (throttle) agar tidak mengebomi API status, dan
    seluruh kegagalan ditelan — polling POS tidak boleh pernah berujung
    HTTP 500.
    """
    license_record = license_for_installation(
        session, device.installation_id, device.device_id
    )
    if license_record is None or license_record.status != "pending":
        return license_record

    order = session.scalar(
        select(Order)
        .where(Order.license_id == license_record.id, Order.status == "pending")
        .order_by(Order.created_at.desc())
        .limit(1)
    )
    if order is None:
        return license_record

    now = time.monotonic()
    last = _LAST_VERIFY.get(order.id)
    if last is not None and (now - last) < VERIFY_MIN_INTERVAL_SECONDS:
        return license_record
    _LAST_VERIFY[order.id] = now
    _prune_verify_cache()

    try:
        refresh_order_status(session, settings, order)
    except Exception:  # noqa: BLE001 — polling tidak boleh gagal
        logger.warning(
            "Verifikasi pembayaran order %s gagal (polling tetap lanjut)",
            order.order_code,
            exc_info=True,
        )
        return license_record

    # refresh_order_status bisa memicu activate_license; muat ulang baris.
    return session.scalar(
        select(License).where(License.id == license_record.id)
    )

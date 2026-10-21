"""Informasi langganan & roadmap pengembangan untuk kartu dashboard POS.

Sumber utama: webserver ``GET /api/pos/status`` (dijalankan di QThread agar
UI tidak tersendat). Bila webserver tidak terjangkau, POS memakai sisa masa
berlaku lisensi lokal sehingga waktu tersisa tetap tampil; daftar fitur
berikutnya dan daftar paket hanya tersedia saat server terhubung.

Struktur info seragam (dict):

{
  "source": "server" | "local",
  "activated": bool,
  "plan": {"code", "name", "cycle", "expires_at",
           "remaining_days", "remaining_text"} | None,
  "plans": [{"code", "name", "cycle", "duration_days", "price_idr"}],
  "roadmap": [{"title", "description", "eta"}],
  "note": str,
}
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from math import ceil
from typing import Any

from PySide6.QtCore import QThread, Signal

from app.services.billing_client import BillingClient, BillingError
from app.services.license_service import LicenseError, LicenseService

logger = logging.getLogger(__name__)

DEVICE_TOKEN_FILE = "billing-device-token.txt"
ROADMAP_PREVIEW_LIMIT = 3

CYCLE_LABELS = {
    "monthly": "Bulanan",
    "yearly": "Tahunan",
    "lifetime": "Selamanya",
    "custom": "Paket khusus",
}


def cycle_label(cycle: str) -> str:
    return CYCLE_LABELS.get(cycle, CYCLE_LABELS["custom"])


def cycle_from_code(plan_code: str) -> str:
    code = (plan_code or "").strip().lower()
    if code == "monthly":
        return "monthly"
    if code == "yearly":
        return "yearly"
    if code == "lifetime":
        return "lifetime"
    return "custom"


def cycle_from_duration(days: float | None) -> str:
    if days is None:
        return "lifetime"
    if days <= 45:
        return "monthly"
    if days <= 400:
        return "yearly"
    return "custom"


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def remaining_from_expiry(expires_at: str | None) -> dict[str, Any]:
    """Sisa masa berlaku dari timestamp ISO → hari + teks siap tampil."""
    expiry = _parse_iso(expires_at)
    if expiry is None:
        return {"days": None, "text": "Berlaku selamanya", "expired": False}
    seconds = int((expiry - datetime.now(timezone.utc)).total_seconds())
    if seconds <= 0:
        return {"days": 0, "text": "Masa berlaku berakhir", "expired": True}
    days = ceil(seconds / 86400)
    if days >= 1:
        text = f"Sisa {days} hari"
    else:
        text = f"Sisa {max(1, ceil(seconds / 3600))} jam"
    return {"days": days, "text": text, "expired": False}


def read_device_token(license_service: LicenseService | None) -> str:
    if license_service is None:
        return ""
    try:
        token_path = license_service.data_dir / DEVICE_TOKEN_FILE
        return token_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def normalize_roadmap(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    items: list[dict[str, str]] = []
    for entry in raw:
        if isinstance(entry, str):
            title = entry.strip()
            if title:
                items.append({"title": title, "description": "", "eta": ""})
            continue
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or entry.get("name") or "").strip()
        if not title:
            continue
        items.append(
            {
                "title": title,
                "description": str(entry.get("description") or "").strip(),
                "eta": str(entry.get("eta") or entry.get("timeline") or "").strip(),
            }
        )
    return items


def normalize_plans(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    plans: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("code") or "").strip()
        if not code:
            continue
        cycle = str(entry.get("cycle") or "").strip() or cycle_from_code(code)
        plans.append(
            {
                "code": code,
                "name": str(entry.get("name") or code).strip(),
                "cycle": cycle,
                "duration_days": entry.get("duration_days"),
                "price_idr": int(entry.get("price_idr") or 0),
            }
        )
    return plans


def normalize_plan(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    code = str(raw.get("code") or "").strip()
    cycle = str(raw.get("cycle") or "").strip() or cycle_from_code(code)
    name = str(raw.get("name") or "").strip() or cycle_label(cycle)
    remaining = remaining_from_expiry(raw.get("expires_at"))
    text = str(raw.get("remaining_text") or "").strip() or remaining["text"]
    days = raw.get("remaining_days")
    if not isinstance(days, int):
        days = remaining["days"]
    return {
        "code": code or cycle,
        "name": name,
        "cycle": cycle,
        "expires_at": str(raw.get("expires_at") or "").strip() or None,
        "remaining_days": days,
        "remaining_text": text,
        "expired": bool(remaining["expired"]),
    }


def local_subscription_info(
    license_service: LicenseService | None,
    note: str = "",
) -> dict[str, Any]:
    """Info langganan dari lisensi terpasang (tanpa jaringan)."""
    info: dict[str, Any] = {
        "source": "local",
        "activated": False,
        "plan": None,
        "plans": [],
        "roadmap": [],
        "note": note,
    }
    if license_service is None:
        if not info["note"]:
            info["note"] = "Info langganan tidak tersedia."
        return info
    try:
        payload = license_service.license_payload()
    except (LicenseError, OSError) as exc:  # pragma: no cover - pertahanan
        logger.warning("Gagal membaca lisensi lokal: %s", exc)
        payload = None
    if payload is None:
        if not info["note"]:
            info["note"] = "Lisensi lokal tidak valid."
        return info

    issued = _parse_iso(payload.get("issued_at"))
    expires_at = payload.get("expires_at")
    expiry = _parse_iso(expires_at)
    duration_days = None
    if issued is not None and expiry is not None:
        duration_days = (expiry - issued).total_seconds() / 86400
    elif expires_at is None:
        duration_days = None
    cycle = cycle_from_duration(duration_days)
    remaining = remaining_from_expiry(expires_at)
    info["activated"] = not remaining["expired"]
    info["plan"] = {
        "code": cycle,
        "name": cycle_label(cycle),
        "cycle": cycle,
        "expires_at": expires_at if isinstance(expires_at, str) else None,
        "remaining_days": remaining["days"],
        "remaining_text": remaining["text"],
        "expired": remaining["expired"],
    }
    if not info["note"]:
        info["note"] = "Data lisensi lokal — sambungkan webserver untuk info terbaru."
    return info


def merge_status(
    status: Any, license_service: LicenseService | None
) -> dict[str, Any]:
    """Gabungkan respons ``/api/pos/status`` dengan cadangan lisensi lokal."""
    if not isinstance(status, dict):
        return local_subscription_info(license_service, note="Respons server tidak valid.")

    subscription = status.get("subscription")
    info: dict[str, Any] = {
        "source": "server",
        "activated": False,
        "plan": None,
        "plans": normalize_plans(status.get("plans")),
        "roadmap": normalize_roadmap(status.get("roadmap")),
        "server_time": str(status.get("server_time") or ""),
        "note": "",
    }
    plan = normalize_plan(
        subscription.get("plan") if isinstance(subscription, dict) else None
    )
    if plan is not None:
        info["plan"] = plan
        info["activated"] = bool(subscription.get("activated"))
        if not info["plans"]:
            info["plans"] = normalize_plans(
                subscription.get("plans") if isinstance(subscription, dict) else None
            )
        return info

    # Perangkat belum terdaftar / lisensi diimpor offline: pakai lisensi lokal.
    local = local_subscription_info(license_service)
    info["plan"] = local["plan"]
    info["activated"] = local["activated"]
    if not info["plans"]:
        info["plans"] = local["plans"]
    info["note"] = local["note"]
    return info


class SubscriptionInfoWorker(QThread):
    """Ambil roadmap + sisa langganan dari webserver di latar belakang.

    Kegagalan jaringan tidak menjadi error: sinyal ``succeeded`` tetap
    memancarkan info berbasis lisensi lokal dengan ``source="local"``.
    """

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        base_url: str,
        license_service: LicenseService | None = None,
        device_token: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._base_url = (base_url or "").strip()
        self._license_service = license_service
        self._device_token = (device_token or "").strip()

    def run(self) -> None:
        if not self._base_url:
            self.succeeded.emit(
                local_subscription_info(
                    self._license_service,
                    note="Webserver billing belum dikonfigurasi.",
                )
            )
            return
        token = self._device_token or read_device_token(self._license_service)
        try:
            status = BillingClient(self._base_url, timeout=8.0).get_status(token)
            self.succeeded.emit(merge_status(status, self._license_service))
        except BillingError as exc:
            self.succeeded.emit(
                local_subscription_info(self._license_service, note=str(exc))
            )
        except Exception as exc:  # noqa: BLE001 — UI tidak boleh crash
            logger.warning("Pengambilan info langganan gagal: %s", exc)
            self.failed.emit(str(exc))

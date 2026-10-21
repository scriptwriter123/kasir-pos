"""Worker latar untuk aktivasi online POS.

Berjalan di QThread: mendaftarkan perangkat (login + kirim .posreq) lalu
mempolling lisensi sampai pembayaran terdeteksi. Saat lisensi aktif,
mengirimkan dokumennya lewat sinyal `succeeded` untuk dipasang di UI thread.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QThread, Signal

from app.services.billing_client import BillingClient, BillingError

POLL_INTERVAL_SECONDS = 10


class OnlineActivationWorker(QThread):
    status = Signal(str)
    succeeded = Signal(object)  # dokumen lisensi (dict)
    failed = Signal(str)

    def __init__(
        self,
        base_url: str,
        *,
        email: str | None = None,
        password: str | None = None,
        posreq_content: str | None = None,
        device_token: str | None = None,
        token_file=None,
        register_first: bool = False,
        store_name: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._base_url = base_url
        self._email = email
        self._password = password
        self._posreq_content = posreq_content
        self._device_token = device_token
        self._token_file = token_file
        self._register_first = register_first
        self._store_name = store_name
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            client = BillingClient(self._base_url)
            if self._register_first:
                self.status.emit("Membuat akun webserver…")
                client.register(
                    self._email or "",
                    self._password or "",
                    self._store_name,
                )
            device_token = self._device_token
            if device_token is None:
                device_token = self._register(client)
            self._poll(client, device_token)
        except BillingError as exc:
            if not self._stop:
                self.failed.emit(str(exc))

    def _register(self, client: BillingClient) -> str:
        self.status.emit("Masuk ke akun webserver…")
        customer_token = client.login(self._email or "", self._password or "")
        self.status.emit("Mendaftarkan perangkat…")
        device_token = client.register_device(
            self._posreq_content or "", customer_token
        )
        self._save_token(device_token)
        return device_token

    def _poll(self, client: BillingClient, device_token: str) -> None:
        self.status.emit("Menunggu pembayaran di webserver…")
        while not self._stop:
            try:
                result = client.poll_license(device_token)
            except BillingError as exc:
                self.status.emit(f"{exc} Mencoba lagi…")
                if self._sleep(POLL_INTERVAL_SECONDS):
                    break
                continue

            status = str(result.get("status", ""))
            document = result.get("document")
            if status == "active" and isinstance(document, dict):
                self.succeeded.emit(document)
                return
            if status in {"revoked", "expired"}:
                self.failed.emit(
                    "Lisensi tidak aktif. Perpanjang langganan di webserver."
                )
                return
            if self._sleep(POLL_INTERVAL_SECONDS):
                break

    def _sleep(self, seconds: int) -> bool:
        """Tidur dengan interval kecil supaya bisa dihentikan. True = berhenti."""
        for _ in range(seconds):
            if self._stop:
                return True
            time.sleep(1)
        return self._stop

    def _save_token(self, device_token: str) -> None:
        if self._token_file is None:
            return
        try:
            self._token_file.parent.mkdir(parents=True, exist_ok=True)
            self._token_file.write_text(device_token + "\n", encoding="utf-8")
        except OSError:
            pass

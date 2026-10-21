"""Klien webserver billing/aktivasi dari sisi POS.

Digunakan untuk aktivasi otomatis: login akun pelanggan, mendaftarkan
perangkat (mengirim .posreq), dan mempolling lisensi sampai pembayaran
terdeteksi lalu dokumen .poslic dapat ditarik.
"""

from __future__ import annotations

from typing import Any

import httpx


class BillingError(RuntimeError):
    pass


class BillingClient:
    def __init__(self, base_url: str, timeout: float = 15.0):
        if not base_url:
            raise BillingError("Alamat webserver billing belum dikonfigurasi.")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _post(self, path: str, payload: dict[str, Any], token: str | None = None):
        headers = self._headers(token)
        try:
            response = httpx.post(
                f"{self.base_url}{path}",
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise BillingError(
                "Tidak dapat menghubungi webserver pembayaran."
            ) from exc
        self._raise_for_status(response)
        return response

    def _get(self, path: str, token: str | None = None):
        try:
            response = httpx.get(
                f"{self.base_url}{path}",
                headers=self._headers(token),
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise BillingError(
                "Tidak dapat menghubungi webserver pembayaran."
            ) from exc
        self._raise_for_status(response)
        return response

    @staticmethod
    def _headers(token: str | None) -> dict[str, str]:
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            detail = response.json().get("detail", "")
        except ValueError:
            detail = ""
        if not detail:
            detail = f"HTTP {response.status_code}"
        raise BillingError(str(detail))

    def login(self, email: str, password: str) -> str:
        data = self._post(
            "/api/auth/login",
            {"email": email, "password": password},
        ).json()
        token = data.get("token")
        if not token:
            raise BillingError("Respons masuk akun tidak valid.")
        return str(token)

    def register(
        self, email: str, password: str, store_name: str = ""
    ) -> None:
        """Buat akun pelanggan baru di webserver."""
        self._post(
            "/api/auth/register",
            {
                "email": email,
                "password": password,
                "store_name": store_name,
            },
        )

    def register_device(
        self, posreq_content: str, customer_token: str
    ) -> str:
        """Kirim .posreq, kembalikan device_token untuk polling."""
        data = self._post(
            "/api/pos/register",
            {"posreq": posreq_content},
            token=customer_token,
        ).json()
        device_token = data.get("device_token")
        if not device_token:
            raise BillingError("Pendaftaran perangkat tidak berhasil.")
        return str(device_token)

    def poll_license(self, device_token: str) -> dict[str, Any]:
        """Kembalikan {"status": str, "document": dict | None}."""
        return self._get("/api/pos/license", token=device_token).json()

    def get_status(self, device_token: str | None = None) -> dict[str, Any]:
        """Roadmap pengembangan + status langganan untuk dashboard POS.

        Token perangkat bersifat opsional: tanpa token server tetap
        mengembalikan roadmap dan daftar paket; dengan token yang sah
        blok ``subscription`` berisi sisa masa berlaku langganan.
        """
        return self._get(
            "/api/pos/status", token=(device_token or "").strip() or None
        ).json()

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AuthorizationError, ValidationError
from app.core.secret_box import SecretBox
from app.models import PaymentWizardState, User

KNOWN_METHODS = ("QRIS_DANA", "QRIS_MIDTRANS", "BANK")

STATUS_NOT_STARTED = "not_started"
STATUS_IN_PROGRESS = "in_progress"
STATUS_PENDING_VERIFICATION = "pending_verification"
STATUS_READY_TO_TEST = "ready_to_test"
STATUS_ACTIVE = "active"
STATUS_FAILED = "failed"

STATUSES: list[tuple[str, str]] = [
    (STATUS_NOT_STARTED, "Belum dimulai"),
    (STATUS_IN_PROGRESS, "Sedang diisi"),
    (STATUS_PENDING_VERIFICATION, "Menunggu verifikasi"),
    (STATUS_READY_TO_TEST, "Siap diuji"),
    (STATUS_ACTIVE, "Aktif"),
    (STATUS_FAILED, "Gagal"),
]

STATUS_LABELS: dict[str, str] = dict(STATUSES)


class PaymentWizardService:
    def __init__(self, session: Session, secret_box: SecretBox | None = None):
        self.session = session
        self.secret = secret_box or SecretBox()

    def get_state(self, method: str) -> PaymentWizardState:
        self._validate_method(method)
        state = self.session.scalar(
            select(PaymentWizardState)
            .where(PaymentWizardState.method == method)
            .limit(1)
        )
        if state is None:
            state = PaymentWizardState(
                method=method, status=STATUS_NOT_STARTED, payload=""
            )
            self.session.add(state)
            self.session.commit()
            self.session.refresh(state)
        return state

    def load_payload(self, method: str) -> dict:
        state = self.get_state(method)
        return self.secret.decrypt(state.payload)

    def save(
        self,
        actor: User,
        *,
        method: str,
        status: str,
        payload: dict,
    ) -> PaymentWizardState:
        self._require_owner(actor)
        self._validate_method(method)
        if status not in STATUS_LABELS:
            raise ValidationError("Status wizard tidak dikenali.")
        if payload and status == STATUS_NOT_STARTED:
            status = STATUS_IN_PROGRESS
        state = self.get_state(method)
        state.status = status
        state.payload = self.secret.encrypt(payload) if payload else ""
        self.session.commit()
        self.session.refresh(state)
        return state

    def test_connection(
        self, payload: dict, method: str = "QRIS_DANA"
    ) -> tuple[bool, str]:
        self._validate_method(method)
        if method == "QRIS_MIDTRANS":
            return self._test_midtrans(payload)
        if method == "BANK":
            return self._test_bank(payload)
        return self._test_dana(payload)

    def _test_dana(self, payload: dict) -> tuple[bool, str]:
        partner = (payload.get("api_partner_id") or "").strip()
        merchant = (payload.get("api_merchant_id") or "").strip()
        private_key = (payload.get("api_private_key") or "").strip()
        environment = (payload.get("api_environment") or "Sandbox").strip()

        if not partner:
            return False, "Partner ID / Client ID belum diisi."
        if not merchant:
            return False, "Merchant ID belum diisi."
        if not private_key:
            return False, "Private key belum diisi."
        if not self._private_key_valid(private_key):
            return False, "Private key PEM tidak valid."

        base_url = settings.dana_base_url.rstrip("/")
        try:
            response = httpx.get(base_url, timeout=4.0)
        except Exception as exc:
            return False, f"Gagal terhubung ke {base_url}: {exc}"
        return True, (
            f"Terhubung ke {base_url} (HTTP {response.status_code}). "
            f"Environment: {environment}."
        )

    def _test_midtrans(self, payload: dict) -> tuple[bool, str]:
        server_key = (payload.get("server_key") or "").strip()
        client_key = (payload.get("client_key") or "").strip()
        environment = (payload.get("api_environment") or "Sandbox").strip()

        if not server_key:
            return False, "Server Key belum diisi."
        if not client_key:
            return False, "Client Key belum diisi."

        base_url = (
            "https://api.sandbox.midtrans.com"
            if environment == "Sandbox"
            else "https://api.midtrans.com"
        )
        probe_url = f"{base_url}/v2/POS-WIZARD-000/status"
        try:
            response = httpx.get(
                probe_url, auth=(server_key, ""), timeout=4.0
            )
        except Exception as exc:
            return False, f"Gagal terhubung ke {base_url}: {exc}"
        if response.status_code == 401:
            return False, "Server Key ditolak Midtrans (HTTP 401). Periksa Server Key."
        if response.status_code in (200, 404):
            return True, (
                f"Server Key valid (HTTP {response.status_code}). "
                f"Environment: {environment}."
            )
        return False, f"Midtrans merespons HTTP {response.status_code}."

    def _test_bank(self, payload: dict) -> tuple[bool, str]:
        mode = (payload.get("transfer_mode") or "manual").strip()
        if mode == "manual":
            bank = (payload.get("bank_name") or "").strip()
            account = (payload.get("account_number") or "").strip()
            if not bank:
                return False, "Nama bank belum dipilih."
            if not account:
                return False, "Nomor rekening belum diisi."
            return True, (
                "Rekening transfer manual siap. Pembayaran dikonfirmasi kasir "
                "setelah memeriksa mutasi atau bukti transfer."
            )

        provider = (payload.get("va_provider") or "").strip()
        if "midtrans" in provider.lower():
            return self._test_midtrans(
                {
                    "server_key": payload.get("va_server_key"),
                    "client_key": payload.get("va_client_key"),
                    "api_environment": payload.get("api_environment"),
                }
            )
        if not provider:
            return False, "Penyedia Virtual Account belum dipilih."
        return False, (
            f"Belum ada pengujian otomatis untuk penyedia {provider}. "
            "Uji nomor VA melalui dashboard penyedia."
        )

    @staticmethod
    def _private_key_valid(private_key: str) -> bool:
        try:
            from cryptography.hazmat.primitives import serialization

            serialization.load_pem_private_key(
                private_key.encode("utf-8"), password=None
            )
            return True
        except Exception:
            return False

    @staticmethod
    def _validate_method(method: str) -> None:
        if method not in KNOWN_METHODS:
            raise ValidationError("Metode pembayaran tidak dikenali.")

    @staticmethod
    def _require_owner(actor: User) -> None:
        if actor.role.name.upper() != "OWNER":
            raise AuthorizationError(
                "Hanya OWNER yang dapat mengubah wizard pembayaran."
            )

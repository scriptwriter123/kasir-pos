from datetime import datetime, timedelta, timezone

from app.core.exceptions import AuthenticationError, PasswordChangeRequired
from app.core.security import verify_password
from app.models import LoginHistory
from app.repositories.user_repository import UserRepository


class AuthService:
    MAX_FAILED_ATTEMPTS = 5
    LOCKOUT_DURATION = timedelta(minutes=15)

    def __init__(self, users: UserRepository):
        self.users = users

    def login(self, username: str, password: str):
        user = self.users.get_by_username(username)
        if not user or not user.is_active:
            raise AuthenticationError("Username atau password salah.")

        now = datetime.now(timezone.utc)
        if user.locked_until and user.locked_until > now:
            raise AuthenticationError("Akun sedang terkunci.")

        if not verify_password(password, user.password_hash):
            user.failed_login_count += 1
            if user.failed_login_count >= self.MAX_FAILED_ATTEMPTS:
                user.locked_until = now + self.LOCKOUT_DURATION
            self.users.session.flush()
            raise AuthenticationError("Username atau password salah.")

        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        # Riwayat login dipakai laporan absensi karyawan.
        self.users.session.add(LoginHistory(user_id=user.id, login_at=now))
        self.users.session.flush()
        if user.must_change_password:
            raise PasswordChangeRequired(user)
        return user

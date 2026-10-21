class POSException(Exception):
    pass


class AuthenticationError(POSException):
    pass


class AuthorizationError(POSException):
    pass


class InsufficientStockError(POSException):
    pass


class PaymentIncompleteError(POSException):
    pass


class ShiftNotOpenError(POSException):
    pass


class LicenseExpiredError(POSException):
    pass


class ValidationError(POSException):
    pass


class PasswordChangeRequired(POSException):
    """Dilemukan saat user login dengan password sementara dan wajib
    mengganti password sebelum dapat menggunakan aplikasi."""
    pass

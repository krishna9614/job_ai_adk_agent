"""Domain errors raised by the service layer and mapped to HTTP responses in app.main."""


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class AuthenticationError(AppError):
    status_code = 401
    code = "not_authenticated"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationFailedError(AppError):
    status_code = 422
    code = "validation_error"


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"


class AuthProviderUnavailableError(AppError):
    status_code = 503
    code = "auth_unavailable"


class InvalidTokenError(AppError):
    """An email link token (confirmation, recovery, email change) is invalid, expired or used."""

    status_code = 400
    code = "invalid_token"


class PasswordReusedError(AppError):
    status_code = 422
    code = "password_reused"

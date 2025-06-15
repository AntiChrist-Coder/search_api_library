from typing import Optional


class SearchAPIError(Exception):
    """Base exception for all Search API errors."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response: Optional[dict] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.response = response
        super().__init__(self.message)


class AuthenticationError(SearchAPIError):
    """Raised when there are authentication issues."""

    pass


class ValidationError(SearchAPIError):
    """Raised when input validation fails."""

    pass


class RateLimitError(SearchAPIError):
    """Raised when rate limit is exceeded."""

    pass


class InsufficientBalanceError(SearchAPIError):
    """Raised when API key has insufficient balance."""

    pass


class ServerError(SearchAPIError):
    """Raised when the server returns an error."""

    pass 
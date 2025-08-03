from typing import Optional, Dict, Any


class SearchAPIError(Exception):
    """Base exception for all Search API errors."""
    
    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response: Optional[Dict[str, Any]] = None,
        error_code: Optional[str] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.response = response
        self.error_code = error_code
        super().__init__(self.message)
    
    def __str__(self) -> str:
        error_info = f"Error: {self.message}"
        if self.status_code:
            error_info += f" (Status: {self.status_code})"
        if self.error_code:
            error_info += f" (Code: {self.error_code})"
        return error_info


class AuthenticationError(SearchAPIError):
    """Raised when there are authentication issues."""
    
    def __init__(self, message: str = "Authentication failed", **kwargs):
        super().__init__(message, **kwargs)


class ValidationError(SearchAPIError):
    """Raised when input validation fails."""
    
    def __init__(self, message: str = "Validation failed", **kwargs):
        super().__init__(message, **kwargs)


class RateLimitError(SearchAPIError):
    """Raised when rate limit is exceeded."""
    
    def __init__(self, message: str = "Rate limit exceeded", **kwargs):
        super().__init__(message, **kwargs)


class InsufficientBalanceError(SearchAPIError):
    """Raised when API key has insufficient balance."""
    
    def __init__(
        self, 
        message: str = "Insufficient balance", 
        current_balance: Optional[float] = None,
        required_credits: Optional[int] = None,
        **kwargs
    ):
        self.current_balance = current_balance
        self.required_credits = required_credits
        
        if current_balance is not None and required_credits is not None:
            message = f"Insufficient balance. Current: {current_balance}, Required: {required_credits}"
        elif current_balance is not None:
            message = f"Insufficient balance. Current balance: {current_balance}"
        
        super().__init__(message, **kwargs)


class ServerError(SearchAPIError):
    """Raised when the server returns an error."""
    
    def __init__(self, message: str = "Server error", **kwargs):
        super().__init__(message, **kwargs)


class NetworkError(SearchAPIError):
    """Raised when there are network connectivity issues."""
    
    def __init__(self, message: str = "Network error", **kwargs):
        super().__init__(message, **kwargs)


class TimeoutError(SearchAPIError):
    """Raised when a request times out."""
    
    def __init__(self, message: str = "Request timeout", **kwargs):
        super().__init__(message, **kwargs)


class ConfigurationError(SearchAPIError):
    """Raised when there are configuration issues."""
    
    def __init__(self, message: str = "Configuration error", **kwargs):
        super().__init__(message, **kwargs) 
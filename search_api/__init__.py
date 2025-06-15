from .client import SearchAPI, SearchAPIConfig
from .exceptions import SearchAPIError
from .models import (
    EmailSearchResult,
    PhoneSearchResult,
    DomainSearchResult,
    Address,
    PhoneNumber,
)

__version__ = "1.0.0"

__all__ = [
    "SearchAPI",
    "SearchAPIConfig",
    "SearchAPIError",
    "EmailSearchResult",
    "PhoneSearchResult",
    "DomainSearchResult",
    "Address",
    "PhoneNumber",
] 
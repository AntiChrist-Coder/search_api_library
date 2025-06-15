from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Union
from decimal import Decimal


@dataclass
class Address:
    """Represents a physical address with optional Zestimate value."""

    street: str
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    zestimate: Optional[Decimal] = None

    def __str__(self) -> str:
        parts = [self.street]
        if self.city:
            parts.append(self.city)
        if self.state:
            parts.append(self.state)
        if self.postal_code:
            parts.append(self.postal_code)
        if self.country:
            parts.append(self.country)
        return ", ".join(parts)


@dataclass
class PhoneNumber:
    """Represents a phone number with validation."""

    number: str
    country_code: str = "US"
    is_valid: bool = True

    def __str__(self) -> str:
        return self.number


@dataclass
class BaseSearchResult:
    """Base class for all search results."""

    name: Optional[str] = None
    dob: Optional[date] = None
    addresses: List[Address] = field(default_factory=list)
    phone_numbers: List[PhoneNumber] = field(default_factory=list)


@dataclass
class EmailSearchResult(BaseSearchResult):
    """Result from email search."""

    email: str
    extra_info: Optional[dict] = None


@dataclass
class PhoneSearchResult(BaseSearchResult):
    """Result from phone search."""

    phone: PhoneNumber
    extra_info: Optional[dict] = None


@dataclass
class DomainSearchResult:
    """Result from domain search."""

    domain: str
    results: List[EmailSearchResult] = field(default_factory=list)
    total_results: int = 0


@dataclass
class SearchAPIConfig:
    """Configuration for the Search API client."""

    api_key: str
    cache_ttl: int = 3600  # 1 hour
    max_retries: int = 3
    timeout: int = 30
    base_url: str = "https://search-api.dev"
    user_agent: str = "SearchAPI-Python/1.0.0" 
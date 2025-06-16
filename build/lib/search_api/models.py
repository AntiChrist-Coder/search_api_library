from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Union, Dict
from decimal import Decimal


@dataclass
class Address:
    """Represents a physical address with optional property details and Zestimate value."""

    street: str
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    zestimate: Optional[Decimal] = None
    zpid: Optional[str] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    living_area: Optional[int] = None
    home_status: Optional[str] = None

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
        address_str = ", ".join(parts)
        
        details = []
        if self.bedrooms is not None:
            details.append(f"{self.bedrooms} beds")
        if self.bathrooms is not None:
            details.append(f"{self.bathrooms} baths")
        if self.living_area is not None:
            details.append(f"{self.living_area} sqft")
        if self.home_status:
            details.append(f"Status: {self.home_status}")
        if details:
            address_str += f" ({', '.join(details)})"
            
        return address_str


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
    age: Optional[int] = None
    emails: List[str] = field(default_factory=list)


@dataclass(init=False)
class EmailSearchResult(BaseSearchResult):
    """Result from email search."""

    email: str

    def __init__(self, email: str, **kwargs):
        super().__init__(**kwargs)
        self.email = email


@dataclass(init=False)
class PhoneSearchResult(BaseSearchResult):
    """Result from phone search."""

    phone: PhoneNumber

    def __init__(self, phone: PhoneNumber, **kwargs):
        super().__init__(**kwargs)
        self.phone = phone


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
    max_retries: int = 3
    timeout: int = 30
    proxy: Optional[Dict[str, str]] = None  # Format: {"http": "http://proxy:port", "https": "https://proxy:port"}
    debug_mode: bool = False
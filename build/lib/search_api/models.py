from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional, Union, Dict, Any
from decimal import Decimal
from enum import Enum


class PhoneFormat(Enum):
    """Phone number format options."""
    INTERNATIONAL = "international"
    NATIONAL = "national"
    E164 = "e164"


class SearchType(Enum):
    """Types of search operations."""
    EMAIL = "email"
    PHONE = "phone"
    DOMAIN = "domain"


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
    last_known_date: Optional[date] = None
    
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
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert address to dictionary."""
        return {
            "street": self.street,
            "city": self.city,
            "state": self.state,
            "postal_code": self.postal_code,
            "country": self.country,
            "zestimate": float(self.zestimate) if self.zestimate else None,
            "zpid": self.zpid,
            "bedrooms": self.bedrooms,
            "bathrooms": self.bathrooms,
            "living_area": self.living_area,
            "home_status": self.home_status,
            "last_known_date": self.last_known_date.isoformat() if self.last_known_date else None,
        }


@dataclass
class PhoneNumber:
    """Represents a phone number with validation and formatting."""
    
    number: str
    country_code: str = "US"
    is_valid: bool = True
    phone_type: Optional[str] = None
    carrier: Optional[str] = None
    
    def __str__(self) -> str:
        return self.number
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert phone number to dictionary."""
        return {
            "number": self.number,
            "country_code": self.country_code,
            "is_valid": self.is_valid,
            "phone_type": self.phone_type,
            "carrier": self.carrier,
        }


@dataclass
class Person:
    """Represents a person with their associated information."""
    
    name: Optional[str] = None
    dob: Optional[date] = None
    age: Optional[int] = None
    
    def __str__(self) -> str:
        if self.name:
            return self.name
        return "Unknown Person"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert person to dictionary."""
        return {
            "name": self.name,
            "dob": self.dob.isoformat() if self.dob else None,
            "age": self.age,
        }


@dataclass
class AccessLog:
    """Represents an access log entry."""
    
    ip_address: str
    last_accessed: Optional[datetime] = None
    user_agent: Optional[str] = None
    endpoint: Optional[str] = None
    method: Optional[str] = None
    status_code: Optional[int] = None
    response_time: Optional[float] = None
    
    def __str__(self) -> str:
        return f"{self.ip_address} - {self.last_accessed}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert access log to dictionary."""
        return {
            "ip_address": self.ip_address,
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None,
            "user_agent": self.user_agent,
            "endpoint": self.endpoint,
            "method": self.method,
            "status_code": self.status_code,
            "response_time": self.response_time,
        }


@dataclass
class BaseSearchResult:
    """Base class for all search results."""
    
    person: Optional[Person] = None
    addresses: List[Address] = field(default_factory=list)
    phone_numbers: List[PhoneNumber] = field(default_factory=list)
    emails: List[str] = field(default_factory=list)
    search_timestamp: Optional[datetime] = None
    total_results: int = 0
    search_cost: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert search result to dictionary."""
        return {
            "person": self.person.to_dict() if self.person else None,
            "addresses": [addr.to_dict() for addr in self.addresses],
            "phone_numbers": [phone.to_dict() for phone in self.phone_numbers],
            "emails": self.emails,
            "search_timestamp": self.search_timestamp.isoformat() if self.search_timestamp else None,
            "total_results": self.total_results,
            "search_cost": self.search_cost,
        }


@dataclass(init=False)
class EmailSearchResult(BaseSearchResult):
    """Result from email search."""
    
    email: str
    email_valid: bool = True
    email_type: Optional[str] = None
    
    def __init__(self, email: str, **kwargs):
        # Extract email-specific fields
        email_valid = kwargs.pop('email_valid', True)
        email_type = kwargs.pop('email_type', None)
        search_cost = kwargs.pop('search_cost', 0.0025)  # Default email search cost
        
        # Initialize parent class
        super().__init__(**kwargs)
        
        # Set email-specific fields
        self.email = email
        self.email_valid = email_valid
        self.email_type = email_type
        self.search_cost = search_cost
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert email search result to dictionary."""
        base_dict = super().to_dict()
        base_dict.update({
            "email": self.email,
            "email_valid": self.email_valid,
            "email_type": self.email_type,
        })
        return base_dict


@dataclass(init=False)
class PhoneSearchResult(BaseSearchResult):
    """Result from phone search."""
    
    phone: PhoneNumber
    
    def __init__(self, phone: PhoneNumber, **kwargs):
        search_cost = kwargs.pop('search_cost', 0.0025)  # Default phone search cost
        super().__init__(**kwargs)
        self.phone = phone
        self.search_cost = search_cost
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert phone search result to dictionary."""
        base_dict = super().to_dict()
        base_dict.update({
            "phone": self.phone.to_dict(),
        })
        return base_dict


@dataclass
class DomainSearchResult:
    """Result from domain search."""
    
    domain: str
    results: List[EmailSearchResult] = field(default_factory=list)
    total_results: int = 0
    domain_valid: bool = True
    search_cost: Optional[float] = None
    
    def __init__(self, domain: str, **kwargs):
        self.domain = domain
        self.results = kwargs.get('results', [])
        self.total_results = kwargs.get('total_results', 0)
        self.domain_valid = kwargs.get('domain_valid', True)
        self.search_cost = kwargs.get('search_cost', 4.00)  # Domain search cost
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert domain search result to dictionary."""
        return {
            "domain": self.domain,
            "results": [result.to_dict() for result in self.results],
            "total_results": self.total_results,
            "domain_valid": self.domain_valid,
            "search_cost": self.search_cost,
        }


@dataclass
class SearchAPIConfig:
    """Configuration for the Search API client."""
    
    api_key: str
    base_url: str = "https://search-api.dev/search.php"
    max_retries: int = 3
    timeout: int = 90
    proxy: Optional[Dict[str, str]] = None
    debug_mode: bool = False
    enable_caching: bool = True
    cache_ttl: int = 3600  # 1 hour
    max_cache_size: int = 1000
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        if not self.api_key:
            raise ValueError("API key is required")
        if self.timeout <= 0:
            raise ValueError("Timeout must be positive")
        if self.max_retries < 0:
            raise ValueError("Max retries must be non-negative")
        if self.cache_ttl <= 0:
            raise ValueError("Cache TTL must be positive")
        if self.max_cache_size <= 0:
            raise ValueError("Max cache size must be positive")


@dataclass
class BalanceInfo:
    """Information about API account balance."""
    
    current_balance: float
    currency: str = "USD"
    last_updated: Optional[datetime] = None
    credit_cost_per_search: Optional[float] = None
    
    def __str__(self) -> str:
        return f"Balance: {self.current_balance} {self.currency}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert balance info to dictionary."""
        return {
            "current_balance": self.current_balance,
            "currency": self.currency,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "credit_cost_per_search": self.credit_cost_per_search,
        }
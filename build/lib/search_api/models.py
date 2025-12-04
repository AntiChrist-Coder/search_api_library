import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional, Union, Dict, Any
from decimal import Decimal
from enum import Enum
import json

# Python 3.10+ supports slots=True in dataclass decorator
_USE_SLOTS = sys.version_info >= (3, 10)

# Helper to conditionally apply slots
def _dataclass_with_slots(*args, **kwargs):
    """Create dataclass with slots if Python 3.10+, otherwise without slots."""
    if _USE_SLOTS:
        kwargs['slots'] = True
    return dataclass(*args, **kwargs)


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
class StructuredAddressComponents:
    """Components of a structured address."""
    
    formatted_address: Optional[str] = None
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    state_code: Optional[str] = None
    postal_code: Optional[str] = None
    zip_code: Optional[str] = None
    zip4: Optional[str] = None
    county: Optional[str] = None
    country: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "formatted_address": self.formatted_address,
            "street": self.street,
            "city": self.city,
            "state": self.state,
            "state_code": self.state_code,
            "postal_code": self.postal_code,
            "zip_code": self.zip_code,
            "zip4": self.zip4,
            "county": self.county,
            "country": self.country,
        }


@dataclass
class StructuredAddress:
    """Structured address with components."""
    
    address: str
    components: Optional[StructuredAddressComponents] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "address": self.address,
            "components": self.components.to_dict() if self.components else None,
        }


@_dataclass_with_slots
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
    state_code: Optional[str] = None
    zip_code: Optional[str] = None
    zip4: Optional[str] = None
    county: Optional[str] = None
    
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
            "state_code": self.state_code,
            "zip_code": self.zip_code,
            "zip4": self.zip4,
            "county": self.county,
        }


@dataclass
class DateObject:
    """Date object with month, day, year."""
    
    month: Optional[int] = None
    day: Optional[int] = None
    year: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "month": self.month,
            "day": self.day,
            "year": self.year,
        }


@dataclass
class PhoneNumberFull:
    """Full phone number information with carrier and metadata."""
    
    number: str
    line_type: Optional[str] = None
    carrier: Optional[str] = None
    date_first_seen: Optional[Dict[str, Any]] = None
    is_spam_report: Optional[bool] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "number": self.number,
            "line_type": self.line_type,
            "carrier": self.carrier,
            "date_first_seen": self.date_first_seen,
            "is_spam_report": self.is_spam_report,
        }


@_dataclass_with_slots
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
class NameRecord:
    """Name record with dates and components."""
    
    name: str
    first: Optional[str] = None
    middle: Optional[str] = None
    last: Optional[str] = None
    date_first_seen: Optional[Dict[str, Any]] = None
    date_last_seen: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "first": self.first,
            "middle": self.middle,
            "last": self.last,
            "date_first_seen": self.date_first_seen,
            "date_last_seen": self.date_last_seen,
        }


@dataclass
class DOBRecord:
    """Date of birth record with age and date object."""
    
    dob: str
    age: Optional[int] = None
    date: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "dob": self.dob,
            "age": self.age,
            "date": self.date,
        }


@dataclass
class RelatedPerson:
    """Related person information."""
    
    name: str
    dob: Optional[str] = None
    age: Optional[int] = None
    relationship: Optional[str] = None
    sub_type: Optional[str] = None
    addresses: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "dob": self.dob,
            "age": self.age,
            "relationship": self.relationship,
            "sub_type": self.sub_type,
            "addresses": self.addresses,
        }


@dataclass
class Crime:
    """Crime information."""
    
    case_number: Optional[str] = None
    crime_type: Optional[str] = None
    crime_county: Optional[str] = None
    offense_code: Optional[str] = None
    offense_description: Optional[str] = None
    court: Optional[str] = None
    charges_filed_date: Optional[str] = None
    disposition_date: Optional[str] = None
    offense_date: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "case_number": self.case_number,
            "crime_type": self.crime_type,
            "crime_county": self.crime_county,
            "offense_code": self.offense_code,
            "offense_description": self.offense_description,
            "court": self.court,
            "charges_filed_date": self.charges_filed_date,
            "disposition_date": self.disposition_date,
            "offense_date": self.offense_date,
        }


@dataclass
class CriminalRecord:
    """Criminal record information."""
    
    source_name: str
    source_state: Optional[str] = None
    case_numbers: List[str] = field(default_factory=list)
    crimes: List[Crime] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "source_name": self.source_name,
            "source_state": self.source_state,
            "case_numbers": self.case_numbers,
            "crimes": [crime.to_dict() for crime in self.crimes],
        }


@_dataclass_with_slots
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


@_dataclass_with_slots
class PricingInfo:
    """Pricing information for a search operation."""
    
    search_cost: float = 0.0
    extra_info_cost: float = 0.0
    zestimate_cost: float = 0.0
    carrier_cost: float = 0.0
    tlo_enrichment_cost: float = 0.0
    total_cost: float = 0.0
    
    def __str__(self) -> str:
        return f"Total: ${self.total_cost:.4f} (Base: ${self.search_cost:.4f}, Extra: ${self.extra_info_cost:.4f}, Zestimate: ${self.zestimate_cost:.4f}, Carrier: ${self.carrier_cost:.4f}, TLO: ${self.tlo_enrichment_cost:.4f})"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "search_cost": self.search_cost,
            "extra_info_cost": self.extra_info_cost,
            "zestimate_cost": self.zestimate_cost,
            "carrier_cost": self.carrier_cost,
            "tlo_enrichment_cost": self.tlo_enrichment_cost,
            "total_cost": self.total_cost,
        }


@_dataclass_with_slots
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
    pricing: Optional[PricingInfo] = None
    # TLO Enrichment fields
    censored_numbers: List[str] = field(default_factory=list)
    addresses_structured: List[StructuredAddress] = field(default_factory=list)
    alternative_names: List[str] = field(default_factory=list)
    all_names: List[NameRecord] = field(default_factory=list)
    all_dobs: List[DOBRecord] = field(default_factory=list)
    related_persons: List[RelatedPerson] = field(default_factory=list)
    criminal_records: List[CriminalRecord] = field(default_factory=list)
    phone_numbers_full: List[PhoneNumberFull] = field(default_factory=list)
    other_emails: List[str] = field(default_factory=list)
    confirmed_numbers: List[str] = field(default_factory=list)
    
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
            "pricing": self.pricing.to_dict() if self.pricing else None,
            "censored_numbers": self.censored_numbers,
            "addresses_structured": [addr.to_dict() for addr in self.addresses_structured],
            "alternative_names": self.alternative_names,
            "all_names": [name.to_dict() for name in self.all_names],
            "all_dobs": [dob.to_dict() for dob in self.all_dobs],
            "related_persons": [person.to_dict() for person in self.related_persons],
            "criminal_records": [record.to_dict() for record in self.criminal_records],
            "phone_numbers_full": [phone.to_dict() for phone in self.phone_numbers_full],
            "other_emails": self.other_emails,
            "confirmed_numbers": self.confirmed_numbers,
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
    pricing: Optional[PricingInfo] = None
    
    def __init__(self, domain: str, **kwargs):
        self.domain = domain
        self.results = kwargs.get('results', [])
        self.total_results = kwargs.get('total_results', 0)
        self.domain_valid = kwargs.get('domain_valid', True)
        self.search_cost = kwargs.get('search_cost', 0.0025)  # Domain search cost
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert domain search result to dictionary."""
        return {
            "domain": self.domain,
            "results": [result.to_dict() for result in self.results],
            "total_results": self.total_results,
            "domain_valid": self.domain_valid,
            "search_cost": self.search_cost,
            "pricing": self.pricing.to_dict() if self.pricing else None,
        }


@dataclass
class SearchAPIConfig:
    """Configuration for the Search API client."""
    
    api_key: str
    base_url: str = "https://search-api.dev/search.php"
    max_retries: int = 1  # Reduced from 3 to 1
    timeout: int = 90
    proxy: Optional[Dict[str, str]] = None
    debug_mode: bool = False
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        if not self.api_key:
            raise ValueError("API key is required")
        if self.timeout <= 0:
            raise ValueError("Timeout must be positive")
        if self.max_retries < 0:
            raise ValueError("Max retries must be non-negative")


@_dataclass_with_slots
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
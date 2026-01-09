import json
import re
import gzip
import logging
import zlib
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional, Union, Any
from urllib.parse import urlencode, quote_plus

import phonenumbers
import requests
from dateutil.parser import parse
from urllib3.util import Retry
from requests.adapters import HTTPAdapter
from requests import Session, Response
from requests.exceptions import RequestException, Timeout, ConnectionError, HTTPError

try:
    import brotli
    BROTLI_AVAILABLE = True
except ImportError:
    BROTLI_AVAILABLE = False

from .exceptions import (
    AuthenticationError,
    InsufficientBalanceError,
    RateLimitError,
    SearchAPIError,
    ServerError,
    NetworkError,
    TimeoutError,
    ConfigurationError,
    ValidationError,
)
from .models import (
    Address,
    BalanceInfo,
    DomainSearchResult,
    EmailSearchResult,
    Person,
    PhoneNumber,
    PhoneSearchResult,
    SearchAPIConfig,
    PhoneFormat,
    SearchType,
    AccessLog,
    StructuredAddress,
    StructuredAddressComponents,
    NameRecord,
    DOBRecord,
    RelatedPerson,
    CriminalRecord,
    Crime,
    PhoneNumberFull,
    PricingInfo,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# Compiled regex patterns for performance optimization
_EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

# Translation table for phone number cleaning (removes spaces, dashes, parentheses, dots)
_PHONE_CLEAN_TABLE = str.maketrans('', '', ' -().')

# Compiled regex patterns for address formatting
_STREET_TYPE_PATTERNS = {
    abbrev: re.compile(rf'\b{re.escape(abbrev)}\b', re.IGNORECASE)
    for abbrev in ["st", "ave", "blvd", "rd", "ln", "dr", "ct", "ter", "pl", "way", 
                   "pkwy", "cir", "sq", "hwy", "bend", "cove"]
}

_STATE_ABBREV_PATTERNS = {
    abbrev: re.compile(rf'\b{re.escape(abbrev)}\b', re.IGNORECASE)
    for abbrev in ["al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
                   "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
                   "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
                   "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
                   "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy"]
}


class SearchAPI:
    """
    A comprehensive client for the Search API with enhanced error handling,
    balance checking, and improved data processing.
    """
    
    def __init__(self, api_key: str = None, config: SearchAPIConfig = None):
        """
        Initialize the Search API client.
        
        Args:
            api_key: API key for authentication
            config: Configuration object with advanced settings
        """
        if config is None:
            if api_key is None:
                raise ConfigurationError("Either api_key or config must be provided")
            config = SearchAPIConfig(api_key=api_key)
        
        self.config = config
        self.session = self._create_session()
        
        self.STREET_TYPE_MAP = {
            "st": "Street", "ave": "Avenue", "blvd": "Boulevard", "rd": "Road",
            "ln": "Lane", "dr": "Drive", "ct": "Court", "ter": "Terrace",
            "pl": "Place", "way": "Way", "pkwy": "Parkway", "cir": "Circle",
            "sq": "Square", "hwy": "Highway", "bend": "Bend", "cove": "Cove",
        }
        
        self.STATE_ABBREVIATIONS = {
            "al": "AL", "ak": "AK", "az": "AZ", "ar": "AR", "ca": "CA",
            "co": "CO", "ct": "CT", "de": "DE", "fl": "FL", "ga": "GA",
            "hi": "HI", "id": "ID", "il": "IL", "in": "IN", "ia": "IA",
            "ks": "KS", "ky": "KY", "la": "LA", "me": "ME", "md": "MD",
            "ma": "MA", "mi": "MI", "mn": "MN", "ms": "MS", "mo": "MO",
            "mt": "MT", "ne": "NE", "nv": "NV", "nh": "NH", "nj": "NJ",
            "nm": "NM", "ny": "NY", "nc": "NC", "nd": "ND", "oh": "OH",
            "ok": "OK", "or": "OR", "pa": "PA", "ri": "RI", "sc": "SC",
            "sd": "SD", "tn": "TN", "tx": "TX", "ut": "UT", "vt": "VT",
            "va": "VA", "wa": "WA", "wv": "WV", "wi": "WI", "wy": "WY",
        }
    
    def _create_session(self) -> Session:
        """Create and configure the HTTP session with connection pooling."""
        session = Session()

        retry_strategy = Retry(
            total=self.config.max_retries,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST"],
            backoff_factor=0.5,
        )
        
        # Configure connection pooling for better performance
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=20,
            pool_block=False
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        session.headers.update({
            "User-Agent": self.config.user_agent,
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate, br" if BROTLI_AVAILABLE else "gzip, deflate",
            "Content-Type": "application/x-www-form-urlencoded",
        })
        
        if self.config.proxy:
            session.proxies.update(self.config.proxy)
        
        return session
    
    def _validate_email(self, email: str, raise_error: bool = False) -> bool:
        """
        Validate email format.
        
        Args:
            email: Email address to validate
            raise_error: If True, raise ValidationError instead of returning False
            
        Returns:
            True if valid, False if invalid (unless raise_error=True)
            
        Raises:
            ValidationError: If email is invalid and raise_error=True
        """
        if not email or not isinstance(email, str):
            if raise_error:
                raise ValidationError("Email address is required and must be a string")
            return False
        
        if not _EMAIL_PATTERN.match(email):
            if raise_error:
                raise ValidationError(f"Invalid email format: {email}")
            return False
        
        return True
    
    def _validate_phone(self, phone: str, raise_error: bool = False) -> bool:
        """
        Validate phone number format.
        
        Args:
            phone: Phone number to validate
            raise_error: If True, raise ValidationError instead of returning False
            
        Returns:
            True if valid, False if invalid (unless raise_error=True)
            
        Raises:
            ValidationError: If phone is invalid and raise_error=True
        """
        if not phone or not isinstance(phone, str):
            if raise_error:
                raise ValidationError("Phone number is required and must be a string")
            return False
        
        # Optimized phone cleaning using translation table
        cleaned_phone = phone.translate(_PHONE_CLEAN_TABLE)
        
        if cleaned_phone.startswith("+"):
            if len(cleaned_phone) >= 10:
                return True
        
        if len(cleaned_phone) == 10 and cleaned_phone.isdigit():
            return True
        
        if len(cleaned_phone) == 11 and cleaned_phone.startswith("1") and cleaned_phone.isdigit():
            return True
        
        if raise_error:
            raise ValidationError(f"Invalid phone number format: {phone}")
        return False
    
    def _validate_domain(self, domain: str, raise_error: bool = False) -> bool:
        """
        Validate domain format.
        
        Args:
            domain: Domain name to validate
            raise_error: If True, raise ValidationError instead of returning False
            
        Returns:
            True if valid, False if invalid (unless raise_error=True)
            
        Raises:
            ValidationError: If domain is invalid and raise_error=True
        """
        if not domain or not isinstance(domain, str):
            if raise_error:
                raise ValidationError("Domain name is required and must be a string")
            return False
        
        domain = domain.lower().strip()
        
        # Optimize domain validation
        domain_clean = domain.replace(".", "").replace("-", "")
        if not domain_clean.isalnum():
            if raise_error:
                raise ValidationError(f"Invalid domain format: {domain} (contains invalid characters)")
            return False
        
        if "." not in domain:
            if raise_error:
                raise ValidationError(f"Invalid domain format: {domain} (missing top-level domain)")
            return False
        
        if domain.startswith(".") or domain.endswith("."):
            if raise_error:
                raise ValidationError(f"Invalid domain format: {domain} (cannot start or end with dot)")
            return False
        
        parts = domain.split(".")
        if len(parts) < 2 or len(parts[-1]) < 2:
            if raise_error:
                raise ValidationError(f"Invalid domain format: {domain} (invalid structure)")
            return False
        
        for part in parts:
            if not part or part.startswith("-") or part.endswith("-"):
                if raise_error:
                    raise ValidationError(f"Invalid domain format: {domain} (invalid label: {part})")
                return False
        
        return True
    
    def _check_balance(self, required_credits: int = 1) -> None:
        """Check if account has sufficient balance for the operation."""
        try:
            balance_info = self.get_balance()
            if balance_info.current_balance < required_credits:
                raise InsufficientBalanceError(
                    f"Insufficient balance. Current: {balance_info.current_balance}, Required: {required_credits}",
                    current_balance=balance_info.current_balance,
                    required_credits=required_credits
                )
        except InsufficientBalanceError:
            raise
        except Exception as e:
            if self.config.debug_mode:
                logger.warning(f"Could not verify balance: {e}")
    
    def get_balance(self) -> BalanceInfo:
        """
        Get current account balance using the correct API endpoint.
        
        Returns:
            BalanceInfo object with current balance details
            
        Raises:
            SearchAPIError: If balance check fails
        """
        try:
            balance_url = f"{self.config.base_url}?action=get_balance&api_key={self.config.api_key}"
            
            if self.config.debug_mode:
                logger.debug(f"Making balance request to: {balance_url}")
            
            response = self.session.get(balance_url, timeout=self.config.timeout)
            
            if response.status_code != 200:
                raise ServerError(f"Balance request failed: {response.status_code}", status_code=response.status_code)
            
            response_data = self._parse_response(response)
            
            if "balance" not in response_data:
                raise ServerError("Invalid balance response from server")
            
            balance_info = BalanceInfo(
                current_balance=float(response_data["balance"]),
                currency="USD",
                last_updated=datetime.now(),
                credit_cost_per_search=0.0025
            )
            
            return balance_info
            
        except Exception as e:
            if isinstance(e, SearchAPIError):
                raise
            raise SearchAPIError(f"Failed to get balance: {str(e)}")
    
    def get_access_logs(self) -> List[AccessLog]:
        """
        Get access logs using the correct API endpoint.
        
        Returns:
            List of AccessLog objects with access information
            
        Raises:
            SearchAPIError: If access logs retrieval fails
        """
        try:
            logs_url = f"{self.config.base_url}?action=get_access_logs&api_key={self.config.api_key}"
            
            if self.config.debug_mode:
                logger.debug(f"Making access logs request to: {logs_url}")
            
            response = self.session.get(logs_url, timeout=self.config.timeout)
            
            if response.status_code != 200:
                raise ServerError(f"Access logs request failed: {response.status_code}", status_code=response.status_code)
            
            response_data = self._parse_response(response)
            
            if "logs" not in response_data:
                raise ServerError("Invalid access logs response from server")
            
            access_logs = []
            for log_entry in response_data["logs"]:
                access_log = AccessLog(
                    ip_address=log_entry.get("ip_address", ""),
                    last_accessed=parse(log_entry["last_accessed"]) if log_entry.get("last_accessed") else None,
                    user_agent=log_entry.get("user_agent"),
                    endpoint=log_entry.get("endpoint"),
                    method=log_entry.get("method"),
                    status_code=log_entry.get("status_code"),
                    response_time=log_entry.get("response_time"),
                )
                access_logs.append(access_log)
            
            return access_logs
            
        except Exception as e:
            if isinstance(e, SearchAPIError):
                raise
            raise SearchAPIError(f"Failed to get access logs: {str(e)}")
    
    def _make_request(self, params: Optional[Dict[str, Any]] = None, method: str = "POST") -> Dict[str, Any]:
        """
        Make HTTP request to the API.
        
        Args:
            params: Request parameters
            method: HTTP method (GET or POST)
            
        Returns:
            Parsed response data
            
        Raises:
            SearchAPIError: For various API errors
        """
        if params is None:
            params = {}
        
        # Sanitize input parameters
        sanitized_params = {}
        for key, value in params.items():
            if isinstance(value, str):
                # Basic sanitization - remove null bytes and control characters
                sanitized_value = value.replace('\x00', '').replace('\r', '').replace('\n', '')
                sanitized_params[key] = sanitized_value.strip()
            else:
                sanitized_params[key] = value
        
        try:
            if self.config.debug_mode:
                logger.debug(f"Making request to {self.config.base_url} with params: {sanitized_params}")
            
            if method == "POST":
                response = self.session.post(
                    self.config.base_url,
                    data=sanitized_params,
                    timeout=self.config.timeout
                )
            elif method == "GET":
                # Use proper URL encoding for all GET requests
                if "phone" in sanitized_params:
                    # Special handling for phone parameter to preserve + sign
                    phone_value = sanitized_params["phone"]
                    # Ensure + is properly encoded using quote_plus
                    phone_value = quote_plus(phone_value)
                    
                    # Build query string manually for phone parameter
                    query_parts = [f"phone={phone_value}"]
                    for key, value in sanitized_params.items():
                        if key != "phone":
                            query_parts.append(f"{quote_plus(str(key))}={quote_plus(str(value))}")
                    query_string = "&".join(query_parts)
                    url = f"{self.config.base_url}?{query_string}"
                    response = self.session.get(url, timeout=self.config.timeout)
                else:
                    # Use standard urlencode for other parameters
                    response = self.session.get(
                        self.config.base_url,
                        params=sanitized_params,
                        timeout=self.config.timeout
                    )
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            if self.config.debug_mode:
                logger.debug(f"Response status: {response.status_code}")
                logger.debug(f"Response headers: {dict(response.headers)}")
            
            if response.status_code == 200:
                result = self._parse_response(response)
                return result
            elif response.status_code == 401:
                raise AuthenticationError(
                    f"Authentication failed: Invalid API key. Please verify your API key is correct.",
                    status_code=401
                )
            elif response.status_code == 402:
                raise InsufficientBalanceError(
                    "Insufficient balance: Your account does not have enough credits to complete this request.",
                    status_code=402
                )
            elif response.status_code == 429:
                raise RateLimitError(
                    "Rate limit exceeded: Too many requests. Please wait before making additional requests.",
                    status_code=429
                )
            elif response.status_code >= 500:
                raise ServerError(
                    f"Server error: The API server encountered an error (HTTP {response.status_code}). "
                    f"Please try again later or contact support if the issue persists.",
                    status_code=response.status_code
                )
            else:
                raise SearchAPIError(
                    f"Request failed with status code {response.status_code}. "
                    f"Please check your request parameters and try again.",
                    status_code=response.status_code
                )
                
        except Timeout:
            raise TimeoutError(
                f"Request timed out after {self.config.timeout} seconds. "
                f"The server may be experiencing high load. Please try again later."
            )
        except ConnectionError:
            raise NetworkError(
                "Network connection error: Unable to connect to the API server. "
                "Please check your internet connection and try again."
            )
        except RequestException as e:
            raise NetworkError(
                f"Request failed: {str(e)}. Please check your network connection and try again."
            )
        except Exception as e:
            raise SearchAPIError(
                f"Unexpected error occurred: {str(e)}. "
                f"If this problem persists, please contact support."
            )
    
    def _parse_response(self, response: Response) -> Dict[str, Any]:
        """
        Parse API response and handle various content encodings.
        
        Args:
            response: HTTP response object
            
        Returns:
            Parsed response data
            
        Raises:
            ServerError: If response parsing fails
        """
        try:
            content = response.content
            content_encoding = response.headers.get("content-encoding", "").lower()
            
            # Decompress content if needed
            if content_encoding == "gzip":
                content = gzip.decompress(content)
            elif content_encoding == "br" and BROTLI_AVAILABLE:
                content = brotli.decompress(content)
            elif content_encoding == "deflate":
                content = zlib.decompress(content)
            
            # Decode content once
            try:
                text_content = content.decode("utf-8")
            except UnicodeDecodeError:
                # Fallback to latin-1 if utf-8 fails
                text_content = content.decode("latin-1")
            
            if self.config.debug_mode:
                logger.debug(f"Raw response content: {text_content}")
            
            # Try to parse as JSON
            try:
                parsed_data = json.loads(text_content)
                if self.config.debug_mode:
                    logger.debug(f"Parsed JSON response: {parsed_data}")
                return parsed_data
            except json.JSONDecodeError:
                # Handle non-JSON responses
                if "error" in text_content.lower():
                    error_msg = text_content.strip()
                    error_lower = error_msg.lower()
                    if "insufficient" in error_lower and "balance" in error_lower:
                        raise InsufficientBalanceError(
                            f"Insufficient balance: {error_msg}",
                            status_code=402
                        )
                    elif "invalid" in error_lower and "key" in error_lower:
                        raise AuthenticationError(
                            f"Authentication failed: {error_msg}",
                            status_code=401
                        )
                    elif "rate limit" in error_lower:
                        raise RateLimitError(
                            f"Rate limit exceeded: {error_msg}",
                            status_code=429
                        )
                    else:
                        raise ServerError(
                            f"Server returned an error: {error_msg}"
                        )
                else:
                    return {"content": text_content}
                    
        except (InsufficientBalanceError, AuthenticationError, RateLimitError, ServerError):
            # Re-raise known exceptions
            raise
        except Exception as e:
            if self.config.debug_mode:
                logger.debug(f"Error parsing response: {e}", exc_info=True)
            raise ServerError(
                f"Failed to parse response: {str(e)}. "
                f"Response status: {response.status_code}, "
                f"Content-Type: {response.headers.get('content-type', 'unknown')}"
            )
    
    def _format_address(self, address_str: str) -> str:
        """Format address string for better readability using compiled regex patterns."""
        if not address_str:
            return ""
        
        # Use pre-compiled patterns for better performance
        for abbrev, pattern in _STREET_TYPE_PATTERNS.items():
            if abbrev in self.STREET_TYPE_MAP:
                address_str = pattern.sub(self.STREET_TYPE_MAP[abbrev], address_str)
        
        for abbrev, pattern in _STATE_ABBREV_PATTERNS.items():
            if abbrev in self.STATE_ABBREVIATIONS:
                address_str = pattern.sub(self.STATE_ABBREVIATIONS[abbrev], address_str)
        
        return address_str.strip()
    
    def _parse_address(self, address_data: Union[str, Dict[str, Any]]) -> Address:
        """Parse address data into Address object."""
        if isinstance(address_data, str):
            address_str = self._format_address(address_data)
            return Address(street=address_str)
        
        if isinstance(address_data, dict):
            if "address" in address_data:
                street = address_data.get("address", "")
                zestimate = address_data.get("zestimate")
                zpid = address_data.get("zpid")
                
                property_details = address_data.get("property_details", {})
                if not isinstance(property_details, dict):
                    property_details = {}
                
                bedrooms = property_details.get("bedrooms") if isinstance(property_details, dict) else None
                bathrooms = property_details.get("bathrooms") if isinstance(property_details, dict) else None
                living_area = property_details.get("living_area") if isinstance(property_details, dict) else None
                home_status = property_details.get("home_status") if isinstance(property_details, dict) else None
                
                # Check if components exist in property_details or address_data
                components = None
                if isinstance(property_details, dict):
                    components = property_details.get("components")
                if not components and isinstance(address_data.get("components"), dict):
                    components = address_data.get("components")
                elif not isinstance(components, dict):
                    components = None
                
                return Address(
                    street=self._format_address(street),
                    city=(property_details.get("city") if isinstance(property_details, dict) else None) or (components.get("city") if isinstance(components, dict) and components else None),
                    state=(property_details.get("state") if isinstance(property_details, dict) else None) or (components.get("state") if isinstance(components, dict) and components else None),
                    postal_code=(property_details.get("zipcode") if isinstance(property_details, dict) else None) or (components.get("postal_code") if isinstance(components, dict) and components else None),
                    country=components.get("country") if isinstance(components, dict) and components else None,
                    zestimate=Decimal(str(zestimate)) if zestimate else None,
                    zpid=zpid,
                    bedrooms=bedrooms,
                    bathrooms=bathrooms,
                    living_area=living_area,
                    home_status=home_status,
                    state_code=components.get("state_code") if isinstance(components, dict) and components else None,
                    zip_code=components.get("zip_code") if isinstance(components, dict) and components else None,
                    zip4=components.get("zip4") if isinstance(components, dict) and components else None,
                    county=components.get("county") if isinstance(components, dict) and components else None,
                )
            else:
                # Check if this is a structured address with components
                components = address_data.get("components")
                if not isinstance(components, dict):
                    components = None
                
                return Address(
                    street=self._format_address(address_data.get("street", "")),
                    city=address_data.get("city") or (components.get("city") if isinstance(components, dict) and components else None),
                    state=address_data.get("state") or (components.get("state") if isinstance(components, dict) and components else None),
                    postal_code=address_data.get("postal_code") or (components.get("postal_code") if isinstance(components, dict) and components else None),
                    country=address_data.get("country") or (components.get("country") if isinstance(components, dict) and components else None),
                    zestimate=Decimal(str(address_data["zestimate"])) if address_data.get("zestimate") else None,
                    zpid=address_data.get("zpid"),
                    bedrooms=address_data.get("bedrooms"),
                    bathrooms=address_data.get("bathrooms"),
                    living_area=address_data.get("living_area"),
                    home_status=address_data.get("home_status"),
                    last_known_date=parse(address_data["last_known"]).date() if address_data.get("last_known") else None,
                    state_code=address_data.get("state_code") or (components.get("state_code") if isinstance(components, dict) and components else None),
                    zip_code=address_data.get("zip_code") or (components.get("zip_code") if isinstance(components, dict) and components else None),
                    zip4=address_data.get("zip4") or (components.get("zip4") if isinstance(components, dict) and components else None),
                    county=address_data.get("county") or (components.get("county") if isinstance(components, dict) and components else None),
                )
        
        return Address(street="")
    
    def _parse_phone_number(self, phone_data: Union[str, Dict], phone_format: Union[str, PhoneFormat] = "international") -> PhoneNumber:
        """
        Parse phone number data into PhoneNumber object.
        
        Args:
            phone_data: Phone number as string or dict
            phone_format: Format for phone numbers (string or PhoneFormat enum)
            
        Returns:
            PhoneNumber object
        """
        # Normalize phone_format to string if enum provided
        if isinstance(phone_format, PhoneFormat):
            phone_format = phone_format.value
        
        if isinstance(phone_data, str):
            # Optimized phone cleaning using translation table
            number = phone_data.translate(_PHONE_CLEAN_TABLE)
            
            if number.startswith("1") and len(number) == 11:
                number = "+" + number
            elif not number.startswith("+"):
                number = "+1" + number
            
            return PhoneNumber(
                number=number,
                is_valid=True,
                phone_type="MOBILE",
                carrier=None,
            )
        
        if isinstance(phone_data, dict):
            # Optimized phone cleaning using translation table
            number = phone_data.get("number", "").translate(_PHONE_CLEAN_TABLE)
            
            if number.startswith("1") and len(number) == 11:
                number = "+" + number
            elif not number.startswith("+"):
                number = "+1" + number
            
            return PhoneNumber(
                number=number,
                country_code=phone_data.get("country_code", "US"),
                is_valid=phone_data.get("is_valid", True),
                phone_type=phone_data.get("phone_type"),
                carrier=phone_data.get("carrier"),
            )
        
        return PhoneNumber(number="")
    
    def _parse_person(self, person_data: Dict[str, Any]) -> Person:
        """Parse person data into Person object."""
        if not isinstance(person_data, dict):
            return Person()
        
        return Person(
            name=person_data.get("name"),
            dob=parse(person_data["dob"]).date() if person_data.get("dob") else None,
            age=person_data.get("age"),
        )
    
    def _parse_structured_address_components(self, components_data: Dict[str, Any]) -> StructuredAddressComponents:
        """Parse structured address components."""
        if not isinstance(components_data, dict):
            return StructuredAddressComponents()
        
        return StructuredAddressComponents(
            formatted_address=components_data.get("formatted_address"),
            street=components_data.get("street"),
            city=components_data.get("city"),
            state=components_data.get("state"),
            state_code=components_data.get("state_code"),
            postal_code=components_data.get("postal_code"),
            zip_code=components_data.get("zip_code"),
            zip4=components_data.get("zip4"),
            county=components_data.get("county"),
            country=components_data.get("country"),
        )
    
    def _parse_structured_address(self, addr_data: Dict[str, Any]) -> StructuredAddress:
        """Parse structured address."""
        if not isinstance(addr_data, dict):
            return StructuredAddress(address="")
        
        components = None
        if "components" in addr_data and addr_data["components"]:
            if isinstance(addr_data["components"], dict):
                components = self._parse_structured_address_components(addr_data["components"])
        
        return StructuredAddress(
            address=addr_data.get("address", ""),
            components=components,
        )
    
    def _parse_name_record(self, name_data: Dict[str, Any]) -> NameRecord:
        """Parse name record."""
        if not isinstance(name_data, dict):
            return NameRecord(name="")
        
        return NameRecord(
            name=name_data.get("name", ""),
            first=name_data.get("first"),
            middle=name_data.get("middle"),
            last=name_data.get("last"),
            date_first_seen=name_data.get("date_first_seen"),
            date_last_seen=name_data.get("date_last_seen"),
        )
    
    def _parse_dob_record(self, dob_data: Dict[str, Any]) -> DOBRecord:
        """Parse DOB record."""
        if not isinstance(dob_data, dict):
            return DOBRecord(dob="")
        
        return DOBRecord(
            dob=dob_data.get("dob", ""),
            age=dob_data.get("age"),
            date=dob_data.get("date"),
        )
    
    def _parse_related_person(self, person_data: Dict[str, Any]) -> RelatedPerson:
        """Parse related person."""
        if not isinstance(person_data, dict):
            return RelatedPerson(name="")
        
        return RelatedPerson(
            name=person_data.get("name", ""),
            dob=person_data.get("dob"),
            age=person_data.get("age"),
            relationship=person_data.get("relationship"),
            sub_type=person_data.get("sub_type"),
            addresses=person_data.get("addresses", []),
        )
    
    def _parse_crime(self, crime_data: Dict[str, Any]) -> Crime:
        """Parse crime information."""
        if not isinstance(crime_data, dict):
            return Crime()
        
        return Crime(
            case_number=crime_data.get("case_number"),
            crime_type=crime_data.get("crime_type"),
            crime_county=crime_data.get("crime_county"),
            offense_code=crime_data.get("offense_code"),
            offense_description=crime_data.get("offense_description"),
            court=crime_data.get("court"),
            charges_filed_date=crime_data.get("charges_filed_date"),
            disposition_date=crime_data.get("disposition_date"),
            offense_date=crime_data.get("offense_date"),
        )
    
    def _parse_criminal_record(self, record_data: Dict[str, Any]) -> CriminalRecord:
        """Parse criminal record."""
        if not isinstance(record_data, dict):
            return CriminalRecord(source_name="")
        
        crimes = []
        if "crimes" in record_data and isinstance(record_data["crimes"], list):
            crimes = [self._parse_crime(crime) for crime in record_data["crimes"]]
        
        return CriminalRecord(
            source_name=record_data.get("source_name", ""),
            source_state=record_data.get("source_state"),
            case_numbers=record_data.get("case_numbers", []),
            crimes=crimes,
        )
    
    def _parse_phone_number_full(self, phone_data: Dict[str, Any]) -> PhoneNumberFull:
        """Parse full phone number information."""
        if not isinstance(phone_data, dict):
            return PhoneNumberFull(number="")
        
        return PhoneNumberFull(
            number=phone_data.get("number", ""),
            line_type=phone_data.get("line_type"),
            carrier=phone_data.get("carrier"),
            date_first_seen=phone_data.get("date_first_seen"),
            is_spam_report=phone_data.get("is_spam_report"),
        )
    
    def search_email(
        self,
        email: str,
        house_value: bool = False,
        extra_info: bool = False,
        carrier_info: bool = False,
        tlo_enrichment: bool = False,
        phone_format: str = "international",
    ) -> EmailSearchResult:
        """
        Search for information by email address.
        
        Args:
            email: Email address to search for
            house_value: Include property value information (Zestimate) (+$0.0015)
            extra_info: Include additional data enrichment (+$0.0015)
            carrier_info: Include carrier information (+$0.0005)
            tlo_enrichment: Include TLO enrichment data (+$0.0030)
            phone_format: Format for phone numbers (string or PhoneFormat enum)
            
        Returns:
            EmailSearchResult object with search results
            
        Raises:
            ValidationError: If email format is invalid
            SearchAPIError: For other API errors
        """
        # Validate email and raise error if invalid
        self._validate_email(email, raise_error=True)
        
        # Normalize phone_format if enum provided
        if isinstance(phone_format, PhoneFormat):
            phone_format = phone_format.value
        
        params = {
            "api_key": self.config.api_key,
            "email": email,
        }
        
        if house_value:
            params["house_value"] = "True"
        if extra_info:
            params["extra_info"] = "True"
        if carrier_info:
            params["carrier_info"] = "True"
        if tlo_enrichment:
            params["tlo_enrichment"] = "True"
        
        response_data = self._make_request(params, method="GET")
        
        return self._parse_email_response(email, response_data)
    
    def _parse_email_response(self, email: str, response_data: Dict[str, Any]) -> EmailSearchResult:
        """Parse email search response."""
        if self.config.debug_mode:
            print(f"DEBUG - Raw response for {email} (type: {type(response_data)}): {response_data}")
            logger.debug(f"Parsing email response (type: {type(response_data)}): {response_data}")
        
        # Handle case where response might be wrapped in a list or results array
        original_response = response_data
        if isinstance(response_data, list) and len(response_data) > 0:
            # If response is a list, take the first element
            response_data = response_data[0]
            if self.config.debug_mode:
                logger.debug(f"Unwrapped list response, using first element: {response_data}")
        elif "results" in response_data and isinstance(response_data["results"], list) and len(response_data["results"]) > 0:
            # If response has a results array, use the first result
            response_data = response_data["results"][0]
            if self.config.debug_mode:
                logger.debug(f"Unwrapped results array, using first result: {response_data}")
        
        # Handle TLO enrichment response structure - data might be nested under '0' key OR at top level
        # Check if data is nested under numeric string keys (like '0', '1', etc.)
        if isinstance(response_data, dict):
            # Look for numeric keys that contain the actual data
            numeric_keys = [k for k in response_data.keys() if isinstance(k, str) and k.isdigit()]
            if numeric_keys:
                # Check if we have actual data fields at top level (name, addresses, numbers, etc.)
                has_top_level_data = any(key in response_data for key in ['name', 'addresses', 'numbers', 'emails'])
                
                # Use nested data if:
                # 1. We have numeric keys with data, AND
                # 2. Either: no top-level data fields, OR nested data has more complete information
                nested_data = response_data[numeric_keys[0]]
                if isinstance(nested_data, dict):
                    # Check if nested data has actual content
                    nested_has_data = any(key in nested_data for key in ['name', 'addresses', 'numbers', 'emails'])
                    
                    if nested_has_data and (not has_top_level_data or len(nested_data) > len([k for k in response_data.keys() if k not in ['_pricing', '_successful_zestimates', '_successful_extra_info', '_successful_carriers', '_successful_tlo_enrichment', 'pagination', 'email', 'emails']])):
                        # Merge nested data into response_data, but keep top-level metadata
                        metadata_keys = ['_pricing', '_successful_zestimates', '_successful_extra_info', 
                                        '_successful_carriers', '_successful_tlo_enrichment', 'pagination']
                        # Preserve metadata from top level (but not email/emails which should come from nested_data)
                        metadata = {k: response_data[k] for k in metadata_keys if k in response_data}
                        # Use nested data as primary, then add metadata (nested_data takes precedence)
                        response_data = {**metadata, **nested_data}
                        if self.config.debug_mode:
                            logger.debug(f"Unwrapped TLO enrichment response from key '{numeric_keys[0]}'")
                    # If top-level has data, keep using top-level (don't overwrite with nested)
                    elif has_top_level_data:
                        if self.config.debug_mode:
                            logger.debug(f"Using top-level data (has data fields), ignoring nested key '{numeric_keys[0]}'")
        
        # Ensure response_data is a dict
        if not isinstance(response_data, dict):
            logger.warning(f"Unexpected response type for email {email}: {type(response_data)}, value: {response_data}")
            # Try to extract from original response
            if isinstance(original_response, dict):
                response_data = original_response
            else:
                # Return empty result if we can't parse
                return EmailSearchResult(
                    email=email,
                    person=None,
                    addresses=[],
                    phone_numbers=[],
                    emails=[],
                    search_timestamp=datetime.now(),
                    total_results=0,
                    search_cost=0.0025,
                    email_valid=True,
                    email_type=None
                )
        
        if "error" in response_data:
            error_msg = response_data["error"]
            if "No data found" in error_msg:
                pricing_info = None
                search_cost = 0.0025
                if "_pricing" in response_data:
                    pricing_data = response_data["_pricing"]
                    if isinstance(pricing_data, dict):
                        pricing_info = PricingInfo(
                            search_cost=pricing_data.get("search_cost", 0.0025),
                            extra_info_cost=pricing_data.get("extra_info_cost", 0.0),
                            zestimate_cost=pricing_data.get("zestimate_cost", 0.0),
                            carrier_cost=pricing_data.get("carrier_cost", 0.0),
                            tlo_enrichment_cost=pricing_data.get("tlo_enrichment_cost", 0.0),
                            total_cost=pricing_data.get("total_cost", pricing_data.get("search_cost", 0.0025)),
                        )
                        search_cost = pricing_info.total_cost
                
                return EmailSearchResult(
                    email=email,
                    person=None,
                    addresses=[],
                    phone_numbers=[],
                    emails=[],
                    search_timestamp=datetime.now(),
                    total_results=0,
                    search_cost=search_cost,
                    pricing=pricing_info,
                    email_valid=True,
                    email_type=None
                )
            elif "Invalid email format" in error_msg:
                raise ValidationError(f"Invalid email format: {email}")
            else:
                raise SearchAPIError(f"Email search failed: {error_msg}")
        
        person = None
        # Check for name field - could be None or empty string
        if "name" in response_data:
            name_value = response_data["name"]
            if name_value and (isinstance(name_value, str) and name_value.strip()):
                person = Person(
                    name=name_value,
                    dob=response_data.get("dob"),
                    age=response_data.get("age")
                )
        
        addresses = []
        if "addresses" in response_data:
            address_data = response_data["addresses"]
            if address_data:  # Check if not None/empty
                if isinstance(address_data, list):
                    addresses = [self._parse_address(addr) for addr in address_data if addr]
                else:
                    addresses = [self._parse_address(address_data)]
        
        phone_numbers = []
        if "numbers" in response_data:
            phone_data = response_data["numbers"]
            if phone_data:  # Check if not None/empty
                if isinstance(phone_data, list):
                    phone_numbers = [self._parse_phone_number(phone, "international") for phone in phone_data if phone]
                else:
                    phone_numbers = [self._parse_phone_number(phone_data, "international")]
        
        emails = response_data.get("emails", [])
        if emails and not isinstance(emails, list):
            emails = [emails] if emails else []
        
        # Parse TLO enrichment fields
        censored_numbers = response_data.get("censored_numbers", [])
        if not isinstance(censored_numbers, list):
            censored_numbers = []
        
        addresses_structured = []
        if "addresses_structured" in response_data:
            addr_structured_data = response_data["addresses_structured"]
            if isinstance(addr_structured_data, list):
                for addr_data in addr_structured_data:
                    if isinstance(addr_data, dict):
                        addresses_structured.append(self._parse_structured_address(addr_data))
            elif isinstance(addr_structured_data, dict):
                addresses_structured.append(self._parse_structured_address(addr_structured_data))
        
        alternative_names = response_data.get("alternative_names", [])
        if not isinstance(alternative_names, list):
            alternative_names = []
        
        all_names = []
        if "all_names" in response_data:
            names_data = response_data["all_names"]
            if isinstance(names_data, list):
                for name_data in names_data:
                    if isinstance(name_data, dict):
                        all_names.append(self._parse_name_record(name_data))
            elif isinstance(names_data, dict):
                all_names.append(self._parse_name_record(names_data))
        
        all_dobs = []
        if "all_dobs" in response_data:
            dobs_data = response_data["all_dobs"]
            if isinstance(dobs_data, list):
                for dob_data in dobs_data:
                    if isinstance(dob_data, dict):
                        all_dobs.append(self._parse_dob_record(dob_data))
            elif isinstance(dobs_data, dict):
                all_dobs.append(self._parse_dob_record(dobs_data))
        
        related_persons = []
        if "related_persons" in response_data:
            persons_data = response_data["related_persons"]
            if isinstance(persons_data, list):
                for person_data in persons_data:
                    if isinstance(person_data, dict):
                        related_persons.append(self._parse_related_person(person_data))
            elif isinstance(persons_data, dict):
                related_persons.append(self._parse_related_person(persons_data))
        
        criminal_records = []
        if "criminal_records" in response_data:
            records_data = response_data["criminal_records"]
            if isinstance(records_data, list):
                for record_data in records_data:
                    if isinstance(record_data, dict):
                        criminal_records.append(self._parse_criminal_record(record_data))
            elif isinstance(records_data, dict):
                criminal_records.append(self._parse_criminal_record(records_data))
        
        phone_numbers_full = []
        if "phone_numbers_full" in response_data:
            phones_data = response_data["phone_numbers_full"]
            if isinstance(phones_data, list):
                for phone_data in phones_data:
                    if isinstance(phone_data, dict):
                        phone_numbers_full.append(self._parse_phone_number_full(phone_data))
            elif isinstance(phones_data, dict):
                phone_numbers_full.append(self._parse_phone_number_full(phones_data))
        
        other_emails = response_data.get("other_emails", [])
        confirmed_numbers = response_data.get("confirmed_numbers", [])
        
        # Extract pricing from _pricing object if available
        search_cost = 0.0025  # Default
        pricing_info = None
        if "_pricing" in response_data:
            pricing_data = response_data["_pricing"]
            if isinstance(pricing_data, dict):
                pricing_info = PricingInfo(
                    search_cost=pricing_data.get("search_cost", 0.0025),
                    extra_info_cost=pricing_data.get("extra_info_cost", 0.0),
                    zestimate_cost=pricing_data.get("zestimate_cost", 0.0),
                    carrier_cost=pricing_data.get("carrier_cost", 0.0),
                    tlo_enrichment_cost=pricing_data.get("tlo_enrichment_cost", 0.0),
                    total_cost=pricing_data.get("total_cost", pricing_data.get("search_cost", 0.0025)),
                )
                search_cost = pricing_info.total_cost
        
        # Get total_results from pagination if available, otherwise calculate
        # Count all data fields including TLO enrichment fields
        total_results = (
            len(addresses) +
            len(phone_numbers) +
            len(emails) +
            (1 if person and person.name else 0) +  # Count person as 1 if present
            len(addresses_structured) +
            len(all_names) +
            len(all_dobs) +
            len(related_persons) +
            len(criminal_records) +
            len(phone_numbers_full) +
            len(censored_numbers) +
            len(confirmed_numbers) +
            len(other_emails) +
            len(alternative_names)
        )
        
        if "pagination" in response_data:
            pagination = response_data["pagination"]
            api_total = pagination.get("total_results")
            if api_total is not None:
                total_results = max(api_total, total_results)
        
        if total_results > 0 and not addresses and not phone_numbers and not emails and not person:
            present_fields = [key for key, value in response_data.items() 
                            if value and key not in ['_pricing', '_successful_zestimates', '_successful_extra_info', 
                                                     '_successful_carriers', '_successful_tlo_enrichment', 'pagination']]
            warning_msg = (f"Email {email}: total_results={total_results} but no parsed data. "
                          f"Present fields: {present_fields}, "
                          f"Keys: {list(response_data.keys())}, "
                          f"name={response_data.get('name')}, "
                          f"addresses={response_data.get('addresses')}, "
                          f"numbers={response_data.get('numbers')}, "
                          f"emails={response_data.get('emails')}")
            logger.warning(warning_msg)
            print(f"WARNING: {warning_msg}")
            if self.config.debug_mode:
                print(f"DEBUG - Full response for {email}: {response_data}")
                logger.debug(f"Full response data: {response_data}")
        
        return EmailSearchResult(
            email=email,
            person=person,
            addresses=addresses,
            phone_numbers=phone_numbers,
            emails=emails,
            search_timestamp=datetime.now(),
            total_results=total_results,
            search_cost=search_cost,
            pricing=pricing_info,
            email_valid=response_data.get("email_valid", True),
            email_type=response_data.get("email_type"),
            censored_numbers=censored_numbers,
            addresses_structured=addresses_structured,
            alternative_names=alternative_names,
            all_names=all_names,
            all_dobs=all_dobs,
            related_persons=related_persons,
            criminal_records=criminal_records,
            phone_numbers_full=phone_numbers_full,
            other_emails=other_emails,
            confirmed_numbers=confirmed_numbers,
        )
    
    def search_phone(
        self,
        phone: str,
        house_value: bool = False,
        extra_info: bool = False,
        carrier_info: bool = False,
        tlo_enrichment: bool = False,
        phone_format: str = "international",
    ) -> List[PhoneSearchResult]:
        """
        Search for information by phone number.
        
        Args:
            phone: Phone number to search for (must start with +1)
            house_value: Include property value information (Zestimate) (+$0.0015)
            extra_info: Include additional data enrichment (+$0.0015)
            carrier_info: Include carrier information (+$0.0005)
            tlo_enrichment: Include TLO enrichment data (+$0.0030)
            phone_format: Format for phone numbers (string or PhoneFormat enum)
            
        Returns:
            List of PhoneSearchResult objects with search results
            
        Raises:
            ValidationError: If phone number format is invalid
            SearchAPIError: For other API errors
        """
        # Validate phone and raise error if invalid
        self._validate_phone(phone, raise_error=True)
        
        # Normalize phone_format if enum provided
        if isinstance(phone_format, PhoneFormat):
            phone_format = phone_format.value
        
        # Optimize phone formatting
        formatted_phone = phone.replace('%2B', '+').replace('%2b', '+')
        
        params = {
            "api_key": self.config.api_key,
            "phone": formatted_phone,
        }
        
        if house_value:
            params["house_value"] = "True"
        if extra_info:
            params["extra_info"] = "True"
        if carrier_info:
            params["carrier_info"] = "True"
        if tlo_enrichment:
            params["tlo_enrichment"] = "True"
        
        response_data = self._make_request(params, method="GET")
        
        return self._parse_phone_response(phone, response_data)
    
    def _parse_phone_response(self, phone: str, response_data: Dict[str, Any]) -> List[PhoneSearchResult]:
        """Parse phone search response."""
        results = []
        
        if self.config.debug_mode:
            logger.debug(f"Parsing phone response: {response_data}")
        
        if "error" in response_data:
            error_msg = response_data["error"]
            if "No data found" in error_msg:
                return []
            elif "Invalid phone number format" in error_msg:
                raise ValidationError(f"Invalid phone number format: {phone}")
            else:
                raise SearchAPIError(f"Phone search failed: {error_msg}")
        
        default_cost = 0.0025
        pricing_info = None
        if "_pricing" in response_data:
            pricing_data = response_data["_pricing"]
            if isinstance(pricing_data, dict):
                pricing_info = PricingInfo(
                    search_cost=pricing_data.get("search_cost", 0.0025),
                    extra_info_cost=pricing_data.get("extra_info_cost", 0.0),
                    zestimate_cost=pricing_data.get("zestimate_cost", 0.0),
                    carrier_cost=pricing_data.get("carrier_cost", 0.0),
                    tlo_enrichment_cost=pricing_data.get("tlo_enrichment_cost", 0.0),
                    total_cost=pricing_data.get("total_cost", pricing_data.get("search_cost", 0.0025)),
                )
                default_cost = pricing_info.total_cost
        
        if isinstance(response_data, list):
            for result_data in response_data:
                result = self._parse_single_phone_result(phone, result_data)
                result.search_cost = default_cost
                result.pricing = pricing_info
                results.append(result)
        elif "results" in response_data and isinstance(response_data["results"], list):
            for result_data in response_data["results"]:
                result = self._parse_single_phone_result(phone, result_data)
                result.search_cost = default_cost
                result.pricing = pricing_info
                results.append(result)
        else:
            result = self._parse_single_phone_result(phone, response_data)
            result.search_cost = default_cost
            result.pricing = pricing_info
            results.append(result)
        
        return results
    
    def _parse_single_phone_result(self, phone: str, result_data: Dict[str, Any]) -> PhoneSearchResult:
        """Parse single phone search result."""
        person = None
        if "name" in result_data and result_data["name"]:
            person = Person(
                name=result_data["name"],
                dob=result_data.get("dob"),
                age=result_data.get("age")
            )
        
        addresses = []
        if "addresses" in result_data:
            address_data = result_data["addresses"]
            if isinstance(address_data, list):
                addresses = [self._parse_address(addr) for addr in address_data]
            else:
                addresses = [self._parse_address(address_data)]
        
        phone_numbers = []
        if "numbers" in result_data:
            phone_data = result_data["numbers"]
            if isinstance(phone_data, list):
                phone_numbers = [self._parse_phone_number(phone_num, "international") for phone_num in phone_data]
            else:
                phone_numbers = [self._parse_phone_number(phone_data, "international")]
        
        emails = result_data.get("emails", [])
        
        # Parse TLO enrichment fields
        censored_numbers = result_data.get("censored_numbers", [])
        if not isinstance(censored_numbers, list):
            censored_numbers = []
        
        addresses_structured = []
        if "addresses_structured" in result_data:
            addr_structured_data = result_data["addresses_structured"]
            if isinstance(addr_structured_data, list):
                for addr_data in addr_structured_data:
                    if isinstance(addr_data, dict):
                        addresses_structured.append(self._parse_structured_address(addr_data))
            elif isinstance(addr_structured_data, dict):
                addresses_structured.append(self._parse_structured_address(addr_structured_data))
        
        alternative_names = result_data.get("alternative_names", [])
        if not isinstance(alternative_names, list):
            alternative_names = []
        
        all_names = []
        if "all_names" in result_data:
            names_data = result_data["all_names"]
            if isinstance(names_data, list):
                for name_data in names_data:
                    if isinstance(name_data, dict):
                        all_names.append(self._parse_name_record(name_data))
            elif isinstance(names_data, dict):
                all_names.append(self._parse_name_record(names_data))
        
        all_dobs = []
        if "all_dobs" in result_data:
            dobs_data = result_data["all_dobs"]
            if isinstance(dobs_data, list):
                for dob_data in dobs_data:
                    if isinstance(dob_data, dict):
                        all_dobs.append(self._parse_dob_record(dob_data))
            elif isinstance(dobs_data, dict):
                all_dobs.append(self._parse_dob_record(dobs_data))
        
        related_persons = []
        if "related_persons" in result_data:
            persons_data = result_data["related_persons"]
            if isinstance(persons_data, list):
                for person_data in persons_data:
                    if isinstance(person_data, dict):
                        related_persons.append(self._parse_related_person(person_data))
            elif isinstance(persons_data, dict):
                related_persons.append(self._parse_related_person(persons_data))
        
        criminal_records = []
        if "criminal_records" in result_data:
            records_data = result_data["criminal_records"]
            if isinstance(records_data, list):
                for record_data in records_data:
                    if isinstance(record_data, dict):
                        criminal_records.append(self._parse_criminal_record(record_data))
            elif isinstance(records_data, dict):
                criminal_records.append(self._parse_criminal_record(records_data))
        
        phone_numbers_full = []
        if "phone_numbers_full" in result_data:
            phones_data = result_data["phone_numbers_full"]
            if isinstance(phones_data, list):
                for phone_data in phones_data:
                    if isinstance(phone_data, dict):
                        phone_numbers_full.append(self._parse_phone_number_full(phone_data))
            elif isinstance(phones_data, dict):
                phone_numbers_full.append(self._parse_phone_number_full(phones_data))
        
        other_emails = result_data.get("other_emails", [])
        confirmed_numbers = result_data.get("confirmed_numbers", [])
        
        total_results = len(addresses) + len(phone_numbers) + len(emails)
        
        main_phone = self._parse_phone_number(phone, "international")
        
        return PhoneSearchResult(
            phone=main_phone,
            person=person,
            addresses=addresses,
            phone_numbers=phone_numbers,
            emails=emails,
            search_timestamp=datetime.now(),
            total_results=total_results,
            search_cost=0.0025,  # Will be set by caller
            censored_numbers=censored_numbers,
            addresses_structured=addresses_structured,
            alternative_names=alternative_names,
            all_names=all_names,
            all_dobs=all_dobs,
            related_persons=related_persons,
            criminal_records=criminal_records,
            phone_numbers_full=phone_numbers_full,
            other_emails=other_emails,
            confirmed_numbers=confirmed_numbers,
        )
    
    def search_domain(self, domain: str) -> DomainSearchResult:
        """
        Search for information by domain name.
        
        Args:
            domain: Domain name to search for
            
        Returns:
            DomainSearchResult object with search results
            
        Raises:
            ValidationError: If domain format is invalid
            SearchAPIError: For other API errors
        """
        # Validate domain and raise error if invalid
        self._validate_domain(domain, raise_error=True)
        
        params = {
            "api_key": self.config.api_key,
            "domain": domain,
        }
        
        response_data = self._make_request(params, method="GET")
        
        return self._parse_domain_response(domain, response_data)
    
    def _parse_domain_response(self, domain: str, response_data: Dict[str, Any]) -> DomainSearchResult:
        """Parse domain search response."""
        results = []
        
        if self.config.debug_mode:
            logger.debug(f"Parsing domain response: {response_data}")
        
        if "error" in response_data:
            error_msg = response_data["error"]
            search_cost = 0.0025
            if "_pricing" in response_data:
                pricing = response_data["_pricing"]
                if isinstance(pricing, dict):
                    search_cost = pricing.get("total_cost", pricing.get("search_cost", 0.0025))
            
            if "No data found" in error_msg:
                pricing_info = None
                if "_pricing" in response_data:
                    pricing_data = response_data["_pricing"]
                    if isinstance(pricing_data, dict):
                        pricing_info = PricingInfo(
                            search_cost=pricing_data.get("search_cost", 0.0025),
                            extra_info_cost=pricing_data.get("extra_info_cost", 0.0),
                            zestimate_cost=pricing_data.get("zestimate_cost", 0.0),
                            carrier_cost=pricing_data.get("carrier_cost", 0.0),
                            tlo_enrichment_cost=pricing_data.get("tlo_enrichment_cost", 0.0),
                            total_cost=pricing_data.get("total_cost", pricing_data.get("search_cost", 0.0025)),
                        )
                        search_cost = pricing_info.total_cost
                
                return DomainSearchResult(
                    domain=domain,
                    results=[],
                    total_results=0,
                    search_cost=search_cost,
                    pricing=pricing_info,
                )
            elif "Invalid domain format" in error_msg:
                raise ValidationError(f"Invalid domain format: {domain}")
            else:
                raise SearchAPIError(f"Domain search failed: {error_msg}")
        
        search_cost = 0.0025
        pricing_info = None
        if "_pricing" in response_data:
            pricing_data = response_data["_pricing"]
            if isinstance(pricing_data, dict):
                pricing_info = PricingInfo(
                    search_cost=pricing_data.get("search_cost", 0.0025),
                    extra_info_cost=pricing_data.get("extra_info_cost", 0.0),
                    zestimate_cost=pricing_data.get("zestimate_cost", 0.0),
                    carrier_cost=pricing_data.get("carrier_cost", 0.0),
                    tlo_enrichment_cost=pricing_data.get("tlo_enrichment_cost", 0.0),
                    total_cost=pricing_data.get("total_cost", pricing_data.get("search_cost", 0.0025)),
                )
                search_cost = pricing_info.total_cost
        
        if isinstance(response_data, list):
            for result_data in response_data:
                email_result = self._parse_single_email_result(result_data)
                email_result.total_results = len(email_result.addresses) + len(email_result.phone_numbers) + len(email_result.emails)
                results.append(email_result)
        elif "results" in response_data and isinstance(response_data["results"], list):
            for result_data in response_data["results"]:
                email_result = self._parse_single_email_result(result_data)
                email_result.total_results = len(email_result.addresses) + len(email_result.phone_numbers) + len(email_result.emails)
                results.append(email_result)
        else:
            email_result = self._parse_single_email_result(response_data)
            email_result.total_results = len(email_result.addresses) + len(email_result.phone_numbers) + len(email_result.emails)
            results.append(email_result)
        
        total_results = len(results)
        
        return DomainSearchResult(
            domain=domain,
            results=results,
            total_results=total_results,
            search_cost=search_cost,
            pricing=pricing_info,
        )
    
    def _parse_single_email_result(self, result_data: Dict[str, Any]) -> EmailSearchResult:
        """Parse single email search result."""
        person = None
        if "name" in result_data and result_data["name"]:
            person = Person(
                name=result_data["name"],
                dob=result_data.get("dob"),
                age=result_data.get("age")
            )
        
        addresses = []
        if "addresses" in result_data:
            address_data = result_data["addresses"]
            if isinstance(address_data, list):
                addresses = [self._parse_address(addr) for addr in address_data]
            else:
                addresses = [self._parse_address(address_data)]
        elif "address" in result_data:
            address_data = result_data["address"]
            if isinstance(address_data, list):
                addresses = [self._parse_address(addr) for addr in address_data]
            else:
                addresses = [self._parse_address(address_data)]
        
        phone_numbers = []
        if "numbers" in result_data:
            phone_data = result_data["numbers"]
            if isinstance(phone_data, list):
                phone_numbers = [self._parse_phone_number(phone, "international") for phone in phone_data]
            else:
                phone_numbers = [self._parse_phone_number(phone_data, "international")]
        elif "phone_numbers" in result_data:
            phone_data = result_data["phone_numbers"]
            if isinstance(phone_data, list):
                phone_numbers = [self._parse_phone_number(phone, "international") for phone in phone_data]
            else:
                phone_numbers = [self._parse_phone_number(phone_data, "international")]
        
        emails = []
        if "emails" in result_data:
            emails = result_data["emails"]
        elif "email" in result_data:
            email_data = result_data["email"]
            if isinstance(email_data, list):
                emails = email_data
            else:
                emails = [email_data]
        
        primary_email = ""
        if "email" in result_data:
            email_data = result_data["email"]
            if isinstance(email_data, list) and email_data:
                primary_email = email_data[0]
            elif isinstance(email_data, str):
                primary_email = email_data
        
        return EmailSearchResult(
            email=primary_email,
            person=person,
            addresses=addresses,
            phone_numbers=phone_numbers,
            emails=emails,
            search_timestamp=datetime.now(),
            total_results=len(addresses) + len(phone_numbers),
            search_cost=0.0025,
            email_valid=result_data.get("email_valid", True),
            email_type=result_data.get("email_type")
        )
    
    def close(self) -> None:
        """Close the client and clean up resources."""
        self.session.close()
    
    def __enter__(self) -> "SearchAPI":
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Optional[Any]) -> None:
        """Context manager exit."""
        self.close()
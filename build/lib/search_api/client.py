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
    CompanyInfo,
    CompanySearchResult,
    DomainSearchResult,
    EducationEntry,
    EmailSearchResult,
    Person,
    PhoneNumber,
    PhoneSearchResult,
    SearchAPIConfig,
    SocialMediaIdentifier,
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
    RecoveryCheckResult,
    RecoveryModule,
    RecoveryModulesResponse,
    UsageStats,
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
    
    def get_access_logs(self, limit: Optional[int] = None) -> List[AccessLog]:
        """
        Get access logs using the correct API endpoint.
        
        Args:
            limit: Optional number of logs to retrieve (default: 100, max: 1000).
        
        Returns:
            List of AccessLog objects with access information
            
        Raises:
            SearchAPIError: If access logs retrieval fails
        """
        try:
            params = {"action": "get_access_logs", "api_key": self.config.api_key}
            if limit is not None:
                params["limit"] = min(max(1, int(limit)), 1000)
            query = "&".join(f"{k}={quote_plus(str(v))}" for k, v in params.items())
            logs_url = f"{self.config.base_url}?{query}"
            
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
                last_accessed = log_entry.get("last_accessed") or log_entry.get("search_time")
                access_log = AccessLog(
                    ip_address=log_entry.get("ip_address", ""),
                    last_accessed=parse(last_accessed) if last_accessed else None,
                    user_agent=log_entry.get("user_agent"),
                    endpoint=log_entry.get("endpoint"),
                    method=log_entry.get("method"),
                    status_code=log_entry.get("status_code"),
                    response_time=log_entry.get("response_time"),
                    search_type=log_entry.get("search_type"),
                    search_cost=float(log_entry["search_cost"]) if log_entry.get("search_cost") is not None else None,
                )
                access_logs.append(access_log)
            
            return access_logs
            
        except Exception as e:
            if isinstance(e, SearchAPIError):
                raise
            raise SearchAPIError(f"Failed to get access logs: {str(e)}")
    
    def get_usage_stats(self) -> UsageStats:
        """
        Get usage statistics (today and total searches/cost).
        
        Returns:
            UsageStats with today_searches, today_cost, total_searches, total_cost
            
        Raises:
            SearchAPIError: If the request fails
        """
        try:
            stats_url = f"{self.config.base_url}?action=get_usage_stats&api_key={self.config.api_key}"
            if self.config.debug_mode:
                logger.debug(f"Making usage stats request to: {stats_url}")
            response = self.session.get(stats_url, timeout=self.config.timeout)
            if response.status_code != 200:
                raise ServerError(f"Usage stats request failed: {response.status_code}", status_code=response.status_code)
            response_data = self._parse_response(response)
            if "usage_stats" not in response_data:
                raise ServerError("Invalid usage stats response from server")
            stats = response_data["usage_stats"]
            today = stats.get("today") or {}
            total = stats.get("total") or {}
            return UsageStats(
                today_searches=int(today.get("searches", 0)),
                today_cost=float(today.get("cost", 0)),
                total_searches=int(total.get("searches", 0)),
                total_cost=float(total.get("cost", 0)),
            )
        except Exception as e:
            if isinstance(e, SearchAPIError):
                raise
            raise SearchAPIError(f"Failed to get usage stats: {str(e)}")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics (e.g. connected, total_keys, redis_used_memory).
        
        Returns:
            Dict with cache stats (structure depends on API; may include connected,
            total_keys, redis_used_memory, fallback_entries, etc.)
            
        Raises:
            SearchAPIError: If the request fails
        """
        try:
            cache_url = f"{self.config.base_url}?action=cache_stats&api_key={self.config.api_key}"
            if self.config.debug_mode:
                logger.debug(f"Making cache stats request to: {cache_url}")
            response = self.session.get(cache_url, timeout=self.config.timeout)
            if response.status_code != 200:
                raise ServerError(f"Cache stats request failed: {response.status_code}", status_code=response.status_code)
            return self._parse_response(response)
        except Exception as e:
            if isinstance(e, SearchAPIError):
                raise
            raise SearchAPIError(f"Failed to get cache stats: {str(e)}")
    
    def get_recovery_modules(self) -> RecoveryModulesResponse:
        """
        Get available recovery check modules and their pricing (for email recovery verification).
        
        Returns:
            RecoveryModulesResponse with modules list and pricing dict (module_name -> price).
            Use these module names in search_email(..., recovery_modules={"module_order": [...], "enabled_modules": [...]}).
            
        Raises:
            SearchAPIError: If the request fails
        """
        try:
            url = f"{self.config.base_url}?action=get_recovery_modules&api_key={self.config.api_key}"
            if self.config.debug_mode:
                logger.debug(f"Making get_recovery_modules request to: {url}")
            response = self.session.get(url, timeout=self.config.timeout)
            if response.status_code != 200:
                raise ServerError(f"Recovery modules request failed: {response.status_code}", status_code=response.status_code)
            data = self._parse_response(response)
            modules = []
            for m in data.get("modules") or []:
                if isinstance(m, dict):
                    name = m.get("module_name") or m.get("name") or ""
                    price = float(m.get("price", 0) or 0)
                    modules.append(RecoveryModule(
                        module_name=name,
                        price=price,
                        display_name=m.get("display_name"),
                        description=m.get("description"),
                        raw=m,
                    ))
                elif isinstance(m, str):
                    modules.append(RecoveryModule(module_name=m, raw={"module_name": m}))
            pricing = data.get("pricing") or {}
            if isinstance(pricing, dict):
                pricing = {k: float(v) for k, v in pricing.items()}
            else:
                pricing = {}
            return RecoveryModulesResponse(modules=modules, pricing=pricing)
        except Exception as e:
            if isinstance(e, SearchAPIError):
                raise
            raise SearchAPIError(f"Failed to get recovery modules: {str(e)}")
    
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

    def _ensure_str_list(
        self, value: Any, dict_key: str = "number"
    ) -> List[str]:
        """Normalize API list to List[str]. Handles items that are str or dict (e.g. confirmed_numbers as list of dicts)."""
        if not value or not isinstance(value, list):
            return []
        out: List[str] = []
        for item in value:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                s = item.get(dict_key) or item.get("email") or item.get("value")
                if s is not None:
                    out.append(str(s))
                else:
                    out.append(str(item))
            else:
                out.append(str(item))
        return out

    def _parse_pricing_from_response(self, pricing_data: Any) -> Optional[PricingInfo]:
        """Build PricingInfo from API _pricing dict. Coerces numeric strings; uses total_cost or total."""
        if not pricing_data or not isinstance(pricing_data, dict):
            return None

        def _float(v: Any, default: float = 0.0) -> float:
            if v is None:
                return default
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, str):
                try:
                    return float(v)
                except (ValueError, TypeError):
                    return default
            return default

        total = _float(
            pricing_data.get("total_cost") or pricing_data.get("total"),
            _float(pricing_data.get("search_cost"), 0.0025),
        )
        return PricingInfo(
            search_cost=_float(pricing_data.get("search_cost"), 0.0),
            extra_info_cost=_float(pricing_data.get("extra_info_cost")),
            zestimate_cost=_float(pricing_data.get("zestimate_cost")),
            carrier_cost=_float(pricing_data.get("carrier_cost")),
            tlo_enrichment_cost=_float(pricing_data.get("tlo_enrichment_cost")),
            recovery_check_cost=_float(pricing_data.get("recovery_check")),
            total_cost=total,
        )

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
        dob = None
        if person_data.get("dob"):
            try:
                dob = parse(person_data["dob"]).date()
            except (TypeError, ValueError):
                pass
        return Person(
            name=person_data.get("name"),
            dob=dob,
            age=person_data.get("age"),
            gender=person_data.get("gender"),
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
    
    def _parse_company_info(self, data: Dict[str, Any]) -> CompanyInfo:
        """Parse company/employment info."""
        if not isinstance(data, dict):
            return CompanyInfo(company_name="")
        return CompanyInfo(
            company_name=data.get("company_name") or data.get("company") or "",
            position=data.get("position"),
        )
    
    def _parse_social_media_identifier(self, data: Dict[str, Any]) -> SocialMediaIdentifier:
        """Parse social media identifier."""
        if not isinstance(data, dict):
            return SocialMediaIdentifier(platform="", identifier="")
        return SocialMediaIdentifier(
            platform=data.get("platform", ""),
            identifier=data.get("identifier", ""),
        )
    
    def _parse_education_entry(self, data: Dict[str, Any]) -> EducationEntry:
        """Parse education entry."""
        if not isinstance(data, dict):
            return EducationEntry(school_name="")
        return EducationEntry(
            school_name=data.get("school_name") or data.get("school") or "",
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
        )
    
    def search_email(
        self,
        email: str,
        house_value: bool = False,
        extra_info: bool = False,
        carrier_info: bool = False,
        tlo_enrichment: bool = False,
        recovery_check: bool = False,
        recovery_modules: Optional[Dict[str, List[str]]] = None,
        phone_format: str = "international",
    ) -> EmailSearchResult:
        """
        Search for information by email address.
        
        Args:
            email: Email address to search for
            house_value: Include property value information (Zestimate) (+$0.0015)
            extra_info: Include additional data enrichment (+$0.0015)
            carrier_info: Include carrier information (+$0.0005)
            tlo_enrichment: Include TLO enrichment data (+$0.0025)
            recovery_check: Enable Phone Recovery Verification for email (variable cost per module)
            recovery_modules: Optional dict with 'module_order' and/or 'enabled_modules' lists
                (e.g. {"module_order": ["yahoo", "outlook"], "enabled_modules": ["yahoo", "outlook"]})
            phone_format: Format for phone numbers (string or PhoneFormat enum)
            
        Returns:
            EmailSearchResult object with search results (includes recovery_check when requested)
            
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
        if recovery_check:
            params["recovery_check"] = "True"
        if recovery_modules and isinstance(recovery_modules, dict):
            if "module_order" in recovery_modules and isinstance(recovery_modules["module_order"], list):
                for i, mod in enumerate(recovery_modules["module_order"]):
                    params[f"recovery_modules[module_order][{i}]"] = mod
            if "enabled_modules" in recovery_modules and isinstance(recovery_modules["enabled_modules"], list):
                for i, mod in enumerate(recovery_modules["enabled_modules"]):
                    params[f"recovery_modules[enabled_modules][{i}]"] = mod
        
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
            # If response has a results array, use the first result but preserve top-level _pricing
            wrapper = response_data
            response_data = dict(wrapper["results"][0]) if isinstance(wrapper["results"][0], dict) else wrapper["results"][0]
            if isinstance(response_data, dict) and "_pricing" in wrapper and "_pricing" not in response_data:
                response_data["_pricing"] = wrapper["_pricing"]
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
                pricing_info = self._parse_pricing_from_response(response_data.get("_pricing"))
                if pricing_info:
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
        if response_data.get("name"):
            person = self._parse_person(response_data)
        else:
            person = None
        
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
        censored_numbers = self._ensure_str_list(
            response_data.get("censored_numbers"), dict_key="number"
        )

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
        
        other_emails = self._ensure_str_list(
            response_data.get("other_emails"), dict_key="email"
        )
        confirmed_numbers = self._ensure_str_list(
            response_data.get("confirmed_numbers"), dict_key="number"
        )

        # Extra-info enrichment fields
        location_metro = response_data.get("location_metro")
        companies = []
        for c in response_data.get("companies") or []:
            if isinstance(c, dict):
                companies.append(self._parse_company_info(c))
        industry = response_data.get("industry")
        linkedin_url = response_data.get("linkedin_url")
        linkedin_id = response_data.get("linkedin_id")
        social_media_identifiers = []
        for s in response_data.get("social_media_identifiers") or []:
            if isinstance(s, dict):
                social_media_identifiers.append(self._parse_social_media_identifier(s))
        education = []
        for e in response_data.get("education") or []:
            if isinstance(e, dict):
                education.append(self._parse_education_entry(e))
        successful_zestimates = response_data.get("_successful_zestimates")
        successful_extra_info = response_data.get("_successful_extra_info")
        successful_carriers = response_data.get("_successful_carriers")
        pagination = response_data.get("pagination")
        
        # Parse recovery check result (email search only)
        recovery_check_result = None
        if "recovery_check" in response_data and isinstance(response_data["recovery_check"], dict):
            rc = response_data["recovery_check"]
            recovery_check_result = RecoveryCheckResult(
                matched=bool(rc.get("matched", False)),
                matched_number=rc.get("matched_number"),
                matched_module=rc.get("matched_module"),
                modules_used=rc.get("modules_used", []) if isinstance(rc.get("modules_used"), list) else [],
                cost=float(rc.get("cost", 0)) if rc.get("cost") is not None else 0.0,
            )
        
        # Extract pricing from _pricing object if available (API returns _pricing with recovery_check when applicable)
        search_cost = 0.0025  # Default
        pricing_info = self._parse_pricing_from_response(response_data.get("_pricing"))
        if pricing_info:
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
            recovery_check=recovery_check_result,
            location_metro=location_metro,
            companies=companies,
            industry=industry,
            linkedin_url=linkedin_url,
            linkedin_id=linkedin_id,
            social_media_identifiers=social_media_identifiers,
            education=education,
            successful_zestimates=successful_zestimates,
            successful_extra_info=successful_extra_info,
            successful_carriers=successful_carriers,
            pagination=pagination,
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
        pricing_info = self._parse_pricing_from_response(response_data.get("_pricing"))
        if pricing_info:
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
        person = self._parse_person(result_data) if result_data.get("name") else None
        
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
        censored_numbers = self._ensure_str_list(
            result_data.get("censored_numbers"), dict_key="number"
        )

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
        
        other_emails = self._ensure_str_list(
            result_data.get("other_emails"), dict_key="email"
        )
        confirmed_numbers = self._ensure_str_list(
            result_data.get("confirmed_numbers"), dict_key="number"
        )

        # Extra-info enrichment
        companies = []
        for c in result_data.get("companies") or []:
            if isinstance(c, dict):
                companies.append(self._parse_company_info(c))
        social_media_identifiers = []
        for s in result_data.get("social_media_identifiers") or []:
            if isinstance(s, dict):
                social_media_identifiers.append(self._parse_social_media_identifier(s))
        education = []
        for e in result_data.get("education") or []:
            if isinstance(e, dict):
                education.append(self._parse_education_entry(e))
        
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
            location_metro=result_data.get("location_metro"),
            companies=companies,
            industry=result_data.get("industry"),
            linkedin_url=result_data.get("linkedin_url"),
            linkedin_id=result_data.get("linkedin_id"),
            social_media_identifiers=social_media_identifiers,
            education=education,
        )
    
    def search_domain(
        self,
        domain: str,
        page: int = 1,
        limit: int = 100,
    ) -> DomainSearchResult:
        """
        Search for information by domain name.
        
        Args:
            domain: Domain name to search for
            page: Page number (1-based)
            limit: Results per page (default 100, max 500)
            
        Returns:
            DomainSearchResult with results list and pagination
            
        Raises:
            ValidationError: If domain format is invalid
            SearchAPIError: For other API errors
        """
        # Validate domain and raise error if invalid
        self._validate_domain(domain, raise_error=True)
        
        params = {
            "api_key": self.config.api_key,
            "domain": domain,
            "page": max(1, page),
            "limit": min(max(1, limit), 500),
        }
        
        response_data = self._make_request(params, method="GET")
        
        return self._parse_domain_response(domain, response_data)
    
    def search_company(
        self,
        company: str,
        country: Optional[str] = None,
        page: int = 1,
        limit: int = 100,
    ) -> CompanySearchResult:
        """
        Search for people/contacts by company name.
        
        Args:
            company: Company name to search for
            country: Optional country code or name to narrow results
            page: Page number (1-based)
            limit: Results per page (default 100, max 500)
            
        Returns:
            CompanySearchResult with results list (same shape as domain search)
            
        Raises:
            SearchAPIError: For API errors
        """
        if not company or not isinstance(company, str) or not company.strip():
            raise ValidationError("Company name is required and must be a non-empty string")
        company = company.strip()
        params = {
            "api_key": self.config.api_key,
            "company": company,
            "page": max(1, page),
            "limit": min(max(1, limit), 500),
        }
        if country:
            params["country"] = country
        response_data = self._make_request(params, method="GET")
        return self._parse_company_response(company, response_data, country=country)
    
    def _parse_company_response(
        self, company: str, response_data: Dict[str, Any], country: Optional[str] = None
    ) -> CompanySearchResult:
        """Parse company search response (same structure as domain)."""
        if "error" in response_data:
            error_msg = response_data["error"]
            search_cost = 0.0025
            pricing_info = self._parse_pricing_from_response(response_data.get("_pricing"))
            if pricing_info:
                search_cost = pricing_info.total_cost
            if "No data found" in error_msg or "too broad" in error_msg.lower():
                return CompanySearchResult(
                    company=company,
                    results=[],
                    total_results=0,
                    search_cost=search_cost,
                    pricing=pricing_info,
                    country=country,
                )
            raise SearchAPIError(f"Company search failed: {error_msg}")
        search_cost = 0.0025
        pricing_info = self._parse_pricing_from_response(response_data.get("_pricing"))
        if pricing_info:
            search_cost = pricing_info.total_cost
        results = []
        raw_results = response_data.get("results") or []
        if isinstance(response_data, list):
            raw_results = response_data
        for result_data in raw_results:
            if isinstance(result_data, dict):
                results.append(self._parse_single_email_result(result_data))
        pagination = response_data.get("pagination")
        total_results = len(results)
        if isinstance(pagination, dict) and pagination.get("total_results") is not None:
            total_results = max(total_results, int(pagination["total_results"]))
        if "_total" in response_data:
            total_results = max(total_results, int(response_data["_total"]))
        return CompanySearchResult(
            company=company,
            results=results,
            total_results=total_results,
            search_cost=search_cost,
            pricing=pricing_info,
            pagination=pagination,
            country=country,
        )
    
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
                pricing_info = self._parse_pricing_from_response(response_data.get("_pricing"))
                if pricing_info:
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
        pricing_info = self._parse_pricing_from_response(response_data.get("_pricing"))
        if pricing_info:
            search_cost = pricing_info.total_cost

        if isinstance(response_data, list):
            for result_data in response_data:
                results.append(self._parse_single_email_result(result_data))
        elif "results" in response_data and isinstance(response_data["results"], list):
            for result_data in response_data["results"]:
                results.append(self._parse_single_email_result(result_data))
        else:
            results.append(self._parse_single_email_result(response_data))
        
        total_results = len(results)
        pagination = response_data.get("pagination")
        if isinstance(pagination, dict) and pagination.get("total_results") is not None:
            total_results = max(total_results, int(pagination["total_results"]))
        if "_total" in response_data:
            total_results = max(total_results, int(response_data["_total"]))
        
        return DomainSearchResult(
            domain=domain,
            results=results,
            total_results=total_results,
            search_cost=search_cost,
            pricing=pricing_info,
            pagination=pagination,
        )
    
    def _parse_single_email_result(self, result_data: Dict[str, Any]) -> EmailSearchResult:
        """Parse single email search result (used for domain/company and batch)."""
        person = self._parse_person(result_data) if result_data.get("name") else None
        
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
            emails = result_data["emails"] if isinstance(result_data["emails"], list) else [result_data["emails"]]
        elif "email" in result_data:
            email_data = result_data["email"]
            if isinstance(email_data, list):
                emails = email_data
            else:
                emails = [email_data] if email_data else []
        
        primary_email = ""
        if emails:
            primary_email = emails[0] if isinstance(emails[0], str) else str(emails[0])
        if "email" in result_data:
            email_data = result_data["email"]
            if isinstance(email_data, list) and email_data:
                primary_email = email_data[0] if isinstance(email_data[0], str) else str(email_data[0])
            elif isinstance(email_data, str):
                primary_email = email_data
        
        # TLO / enrichment fields (domain, company, and rich email/phone results)
        censored_numbers = self._ensure_str_list(
            result_data.get("censored_numbers"), dict_key="number"
        )
        addresses_structured = []
        if "addresses_structured" in result_data:
            for addr_data in result_data["addresses_structured"] or []:
                if isinstance(addr_data, dict):
                    addresses_structured.append(self._parse_structured_address(addr_data))
        alternative_names = result_data.get("alternative_names") or []
        if not isinstance(alternative_names, list):
            alternative_names = []
        all_names = []
        if "all_names" in result_data:
            for name_data in result_data["all_names"] or []:
                if isinstance(name_data, dict):
                    all_names.append(self._parse_name_record(name_data))
        all_dobs = []
        if "all_dobs" in result_data:
            for dob_data in result_data["all_dobs"] or []:
                if isinstance(dob_data, dict):
                    all_dobs.append(self._parse_dob_record(dob_data))
        related_persons = []
        if "related_persons" in result_data:
            for person_data in result_data["related_persons"] or []:
                if isinstance(person_data, dict):
                    related_persons.append(self._parse_related_person(person_data))
        criminal_records = []
        if "criminal_records" in result_data:
            for record_data in result_data["criminal_records"] or []:
                if isinstance(record_data, dict):
                    criminal_records.append(self._parse_criminal_record(record_data))
        phone_numbers_full = []
        if "phone_numbers_full" in result_data:
            for phone_data in result_data["phone_numbers_full"] or []:
                if isinstance(phone_data, dict):
                    phone_numbers_full.append(self._parse_phone_number_full(phone_data))
        other_emails = self._ensure_str_list(
            result_data.get("other_emails"), dict_key="email"
        )
        confirmed_numbers = self._ensure_str_list(
            result_data.get("confirmed_numbers"), dict_key="number"
        )

        # Extra-info enrichment
        companies = []
        for c in result_data.get("companies") or []:
            if isinstance(c, dict):
                companies.append(self._parse_company_info(c))
        social_media_identifiers = []
        for s in result_data.get("social_media_identifiers") or []:
            if isinstance(s, dict):
                social_media_identifiers.append(self._parse_social_media_identifier(s))
        education = []
        for e in result_data.get("education") or []:
            if isinstance(e, dict):
                education.append(self._parse_education_entry(e))
        
        total_results = (
            len(addresses) + len(phone_numbers) + len(emails) +
            len(addresses_structured) + len(all_names) + len(all_dobs) +
            len(related_persons) + len(criminal_records) + len(phone_numbers_full) +
            len(censored_numbers) + len(confirmed_numbers) + len(other_emails) + len(alternative_names) +
            (1 if person and person.name else 0)
        )

        pricing_info = self._parse_pricing_from_response(result_data.get("_pricing"))
        search_cost = pricing_info.total_cost if pricing_info else 0.0025

        return EmailSearchResult(
            email=primary_email or (emails[0] if emails else ""),
            person=person,
            addresses=addresses,
            phone_numbers=phone_numbers,
            emails=emails,
            search_timestamp=datetime.now(),
            total_results=total_results,
            search_cost=search_cost,
            pricing=pricing_info,
            email_valid=result_data.get("email_valid", True),
            email_type=result_data.get("email_type"),
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
            location_metro=result_data.get("location_metro"),
            companies=companies,
            industry=result_data.get("industry"),
            linkedin_url=result_data.get("linkedin_url"),
            linkedin_id=result_data.get("linkedin_id"),
            social_media_identifiers=social_media_identifiers,
            education=education,
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
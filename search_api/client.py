import json
import re
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Union
from urllib.parse import urljoin

import phonenumbers
import requests
from cachetools import TTLCache
from dateutil.parser import parse

from .exceptions import (
    AuthenticationError,
    InsufficientBalanceError,
    RateLimitError,
    SearchAPIError,
    ServerError,
    ValidationError,
)
from .models import (
    Address,
    DomainSearchResult,
    EmailSearchResult,
    PhoneNumber,
    PhoneSearchResult,
    SearchAPIConfig,
)

# Major email domains that are not allowed for domain search
MAJOR_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "aol.com",
    "icloud.com",
    "live.com",
    "msn.com",
    "comcast.net",
    "me.com",
    "mac.com",
    "att.net",
    "verizon.net",
    "protonmail.com",
    "zoho.com",
    "yandex.com",
    "mail.com",
    "gmx.com",
    "rocketmail.com",
    "yahoo.co.uk",
    "btinternet.com",
    "bellsouth.net",
}

# Street type mapping
STREET_TYPE_MAP = {
    "st": "Street",
    "ave": "Avenue",
    "blvd": "Boulevard",
    "rd": "Road",
    "ln": "Lane",
    "dr": "Drive",
    "ct": "Court",
    "ter": "Terrace",
    "pl": "Place",
    "way": "Way",
    "pkwy": "Parkway",
    "cir": "Circle",
    "sq": "Square",
    "hwy": "Highway",
    "bend": "Bend",
    "cove": "Cove",
}

# State abbreviations mapping
STATE_ABBREVIATIONS = {
    "al": "AL",
    "ak": "AK",
    "az": "AZ",
    "ar": "AR",
    "ca": "CA",
    "co": "CO",
    "ct": "CT",
    "de": "DE",
    "fl": "FL",
    "ga": "GA",
    "hi": "HI",
    "id": "ID",
    "il": "IL",
    "in": "IN",
    "ia": "IA",
    "ks": "KS",
    "ky": "KY",
    "la": "LA",
    "me": "ME",
    "md": "MD",
    "ma": "MA",
    "mi": "MI",
    "mn": "MN",
    "ms": "MS",
    "mo": "MO",
    "mt": "MT",
    "ne": "NE",
    "nv": "NV",
    "nh": "NH",
    "nj": "NJ",
    "nm": "NM",
    "ny": "NY",
    "nc": "NC",
    "nd": "ND",
    "oh": "OH",
    "ok": "OK",
    "or": "OR",
    "pa": "PA",
    "ri": "RI",
    "sc": "SC",
    "sd": "SD",
    "tn": "TN",
    "tx": "TX",
    "ut": "UT",
    "vt": "VT",
    "va": "VA",
    "wa": "WA",
    "wv": "WV",
    "wi": "WI",
    "wy": "WY",
}


class SearchAPI:
    """Main client for interacting with the Search API."""

    def __init__(self, api_key: str = None, config: SearchAPIConfig = None):
        """Initialize the Search API client.

        Args:
            api_key: Your API key
            config: Optional configuration object
        """
        if config is None:
            if api_key is None:
                raise ValueError("Either api_key or config must be provided")
            config = SearchAPIConfig(api_key=api_key)

        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": config.user_agent,
                "Accept": "application/json",
            }
        )
        self.cache = TTLCache(maxsize=1000, ttl=config.cache_ttl)

    def _make_request(
        self,
        endpoint: str,
        params: Optional[Dict] = None,
        method: str = "GET",
        data: Optional[Dict] = None,
    ) -> Dict:
        """Make a request to the Search API.

        Args:
            endpoint: API endpoint
            params: Query parameters
            method: HTTP method
            data: Request body data

        Returns:
            API response as dictionary

        Raises:
            SearchAPIError: If the request fails
        """
        url = urljoin(self.config.base_url, endpoint)
        params = params or {}
        params["api_key"] = self.config.api_key

        try:
            response = self.session.request(
                method,
                url,
                params=params,
                json=data,
                timeout=self.config.timeout,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid API key", e.response.status_code)
            elif e.response.status_code == 402:
                raise InsufficientBalanceError(
                    "Insufficient balance", e.response.status_code
                )
            elif e.response.status_code == 429:
                raise RateLimitError("Rate limit exceeded", e.response.status_code)
            elif e.response.status_code >= 500:
                raise ServerError("Server error", e.response.status_code)
            else:
                raise SearchAPIError(
                    f"HTTP error: {e.response.text}",
                    e.response.status_code,
                    e.response.json() if e.response.text else None,
                )
        except requests.exceptions.RequestException as e:
            raise SearchAPIError(f"Request error: {str(e)}")

    def _format_address(self, address_str: str) -> str:
        """Format an address string according to standard conventions.

        Args:
            address_str: Raw address string

        Returns:
            Formatted address string
        """
        parts = [part.strip() for part in address_str.split(",") if part.strip()]
        formatted_parts = []

        for part in parts:
            words = part.split()
            for i, word in enumerate(words):
                word_lower = word.lower()
                words[i] = STREET_TYPE_MAP.get(word_lower, word.title())
            formatted_parts.append(" ".join(words))

        if formatted_parts:
            last_part = formatted_parts[-1].split()
            if len(last_part) > 1 and last_part[-1].isdigit():
                state = last_part[-2].lower()
                if state in STATE_ABBREVIATIONS:
                    last_part[-2] = STATE_ABBREVIATIONS[state]
                formatted_parts[-1] = " ".join(last_part)
            elif last_part:
                state = last_part[-1].lower()
                if state in STATE_ABBREVIATIONS:
                    last_part[-1] = STATE_ABBREVIATIONS[state]
                    formatted_parts[-1] = " ".join(last_part)

        return ", ".join(formatted_parts)

    def _parse_address(self, address_data: Union[str, Dict]) -> Address:
        """Parse address data into an Address object.

        Args:
            address_data: Address data as string or dictionary

        Returns:
            Address object
        """
        if isinstance(address_data, str):
            return Address(street=self._format_address(address_data))
        else:
            return Address(
                street=address_data.get("street", ""),
                city=address_data.get("city"),
                state=address_data.get("state"),
                postal_code=address_data.get("postal_code"),
                country=address_data.get("country"),
                zestimate=Decimal(str(address_data["zestimate"]))
                if "zestimate" in address_data
                else None,
            )

    def _parse_phone_number(self, phone_str: str) -> PhoneNumber:
        """Parse and validate a phone number.

        Args:
            phone_str: Phone number string

        Returns:
            PhoneNumber object
        """
        try:
            number = phonenumbers.parse(phone_str, "US")
            is_valid = phonenumbers.is_valid_number(number)
            formatted = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
            return PhoneNumber(number=formatted, is_valid=is_valid)
        except phonenumbers.NumberParseException:
            return PhoneNumber(number=phone_str, is_valid=False)

    def search_email(
        self, email: str, include_house_value: bool = False, include_extra_info: bool = False
    ) -> EmailSearchResult:
        """Search for information by email address.

        Args:
            email: Email address to search
            include_house_value: Whether to include house value information
            include_extra_info: Whether to include extra information

        Returns:
            EmailSearchResult object

        Raises:
            ValidationError: If the email is invalid
            SearchAPIError: If the request fails
        """
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            raise ValidationError("Invalid email format")

        cache_key = f"email_{email}_{include_house_value}_{include_extra_info}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        params = {
            "email": email,
            "house_value": str(include_house_value).lower(),
            "extra_info": str(include_extra_info).lower(),
        }

        response = self._make_request("search.php", params)
        if "error" in response:
            raise SearchAPIError(response["error"])

        result = EmailSearchResult(
            email=email,
            name=response.get("name"),
            dob=parse(response["dob"]).date() if response.get("dob") else None,
            addresses=[
                self._parse_address(addr) for addr in response.get("addresses", [])
            ],
            phone_numbers=[
                self._parse_phone_number(num) for num in response.get("numbers", [])
            ],
            extra_info=response.get("extra_info"),
        )

        self.cache[cache_key] = result
        return result

    def search_phone(
        self, phone: str, include_house_value: bool = False, include_extra_info: bool = False
    ) -> PhoneSearchResult:
        """Search for information by phone number.

        Args:
            phone: Phone number to search
            include_house_value: Whether to include house value information
            include_extra_info: Whether to include extra information

        Returns:
            PhoneSearchResult object

        Raises:
            ValidationError: If the phone number is invalid
            SearchAPIError: If the request fails
        """
        phone_number = self._parse_phone_number(phone)
        if not phone_number.is_valid:
            raise ValidationError("Invalid phone number format")

        cache_key = f"phone_{phone}_{include_house_value}_{include_extra_info}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        params = {
            "phone": phone,
            "house_value": str(include_house_value).lower(),
            "extra_info": str(include_extra_info).lower(),
        }

        response = self._make_request("search.php", params)
        if "error" in response:
            raise SearchAPIError(response["error"])

        result = PhoneSearchResult(
            phone=phone_number,
            name=response.get("name"),
            dob=parse(response["dob"]).date() if response.get("dob") else None,
            addresses=[
                self._parse_address(addr) for addr in response.get("addresses", [])
            ],
            phone_numbers=[
                self._parse_phone_number(num) for num in response.get("numbers", [])
            ],
            extra_info=response.get("extra_info"),
        )

        self.cache[cache_key] = result
        return result

    def search_domain(self, domain: str) -> DomainSearchResult:
        """Search for information by domain name.

        Args:
            domain: Domain name to search

        Returns:
            DomainSearchResult object

        Raises:
            ValidationError: If the domain is invalid or is a major domain
            SearchAPIError: If the request fails
        """
        domain = domain.lower().strip()
        if not re.match(r"^[a-z0-9]+([\-\.]{1}[a-z0-9]+)*\.[a-z]{2,}$", domain):
            raise ValidationError("Invalid domain format")

        if domain in MAJOR_DOMAINS:
            raise ValidationError("Searching major domains is not allowed")

        cache_key = f"domain_{domain}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        params = {"domain": domain}
        response = self._make_request("search.php", params)
        if "error" in response:
            raise SearchAPIError(response["error"])

        results = []
        for item in response.get("results", []):
            email_result = EmailSearchResult(
                email=item["email"],
                name=item.get("name"),
                addresses=[
                    self._parse_address(addr) for addr in item.get("addresses", [])
                ],
                phone_numbers=[
                    self._parse_phone_number(num) for num in item.get("phone_numbers", [])
                ],
            )
            results.append(email_result)

        result = DomainSearchResult(
            domain=domain,
            results=results,
            total_results=len(results),
        )

        self.cache[cache_key] = result
        return result 
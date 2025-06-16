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
from urllib3.util import Retry
from requests.adapters import HTTPAdapter
import logging
from requests import Session, Response
from requests.exceptions import RequestException, Timeout, ConnectionError, HTTPError

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

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

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
    CHROME_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    BASE_URL = "https://search-api.dev/search.php"

    def __init__(self, api_key: str = None, config: SearchAPIConfig = None):
        if config is None:
            if api_key is None:
                raise ValueError("Either api_key or config must be provided")
            config = SearchAPIConfig(api_key=api_key)

        self.config = config
        
        if config.debug_mode:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            
            logger.handlers = []
            logger.addHandler(handler)
            logger.setLevel(logging.DEBUG)
            logger.debug("Debug mode enabled")
        else:
            logger.setLevel(logging.WARNING)
        
        self.session = requests.Session()
        
        retry_strategy = Retry(
            total=config.max_retries,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            respect_retry_after_header=True
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        if config.debug_mode:
            logger.debug(f"Configured retry strategy: max_retries={config.max_retries}, backoff_factor=0.5")
        
        self.session.headers.update(
            {
                "User-Agent": self.CHROME_USER_AGENT,
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0"
            }
        )
        
        if config.proxy:
            self.session.proxies.update(config.proxy)
            if config.debug_mode:
                logger.debug(f"Configured proxy: {config.proxy}")

    def _make_request(
        self, params: Optional[Dict] = None
    ) -> Dict:
        if params is None:
            params = {}
        params['api_key'] = self.config.api_key
        
        if self.config.debug_mode:
            logger.debug(f"Making GET request to {self.BASE_URL}")
            logger.debug(f"Request params: {params}")

        try:
            connect_timeout = min(5, self.config.timeout)
            read_timeout = self.config.timeout - connect_timeout

            response = self.session.get(
                url=self.BASE_URL,
                params=params,
                timeout=(connect_timeout, read_timeout),
            )
            response.raise_for_status()

            if not response.text.strip():
                if self.config.debug_mode:
                    logger.warning(f"Empty response received from {self.BASE_URL}")
                return {}

            try:
                result = response.json()
                if self.config.debug_mode:
                    logger.debug(f"Response received: {result}")
                return result
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON response: {response.text}")
                raise SearchAPIError(f"Invalid JSON response: {str(e)}")

        except Timeout as e:
            logger.error(f"Request timed out after {self.config.timeout}s: {str(e)}")
            raise SearchAPIError(f"Request timed out after {self.config.timeout}s")
        except ConnectionError as e:
            logger.error(f"Connection error: {str(e)}")
            raise SearchAPIError(f"Connection error: {str(e)}")
        except HTTPError as e:
            logger.error(f"HTTP error: {str(e)}")
            raise SearchAPIError(f"HTTP error: {str(e)}")
        except RequestException as e:
            logger.error(f"Request failed: {str(e)}")
            raise SearchAPIError(f"Request failed: {str(e)}")

    def _format_address(self, address_str: str) -> str:
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
        if isinstance(address_data, str):
            try:
                parts = [part.strip() for part in address_data.split(",")]
                if len(parts) < 3:
                    return Address(street=address_data)
                    
                street = parts[0] if parts else ""
                city = parts[1] if len(parts) > 1 else None
                state = parts[2] if len(parts) > 2 else None
                postal_code = parts[3] if len(parts) > 3 else None
                country = parts[4] if len(parts) > 4 else None
                
                if state:
                    state = state.strip().upper()
                if postal_code:
                    postal_code = postal_code.strip()
                if country:
                    country = country.strip().upper()
                    
                return Address(
                    street=street,
                    city=city,
                    state=state,
                    postal_code=postal_code,
                    country=country
                )
            except Exception:
                return Address(street=address_data)
        else:
            address_str = address_data.get("address", "")
            property_details = address_data.get("property_details", {})
            
            if property_details:
                street = property_details.get("street_address", "")
                city = property_details.get("city")
                state = property_details.get("state")
                postal_code = property_details.get("zipcode")
                zpid = property_details.get("zpid")
                bedrooms = property_details.get("bedrooms")
                bathrooms = property_details.get("bathrooms")
                living_area = property_details.get("living_area")
                home_status = property_details.get("home_status")
            else:
                parts = [part.strip() for part in address_str.split(",")]
                street = parts[0] if parts else ""
                city = parts[1] if len(parts) > 1 else None
                state = parts[2] if len(parts) > 2 else None
                postal_code = parts[3] if len(parts) > 3 else None
                zpid = None
                bedrooms = None
                bathrooms = None
                living_area = None
                home_status = None
            
            address_kwargs = {
                "street": street,
                "city": city,
                "state": state,
                "postal_code": postal_code,
                "country": None,
                "zestimate": Decimal(str(address_data.get("zestimate"))) if address_data.get("zestimate") else None,
                "zpid": zpid,
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,
                "living_area": living_area,
                "home_status": home_status,
            }
            
            return Address(**address_kwargs)

    def _parse_phone_number(self, phone_str: str, format: str = "international") -> PhoneNumber:
        try:
            number = phonenumbers.parse(phone_str, "US")
            is_valid = phonenumbers.is_valid_number(number)
            
            if format == "local":
                formatted = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.NATIONAL)
            else:
                formatted = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
                
            return PhoneNumber(number=formatted, is_valid=is_valid)
        except phonenumbers.NumberParseException:
            return PhoneNumber(number=phone_str, is_valid=False)

    def search_email(self, email: str, include_house_value: bool = False, include_extra_info: bool = False, phone_format: str = "international") -> EmailSearchResult:
        if self.config.debug_mode:
            logger.debug(f"Searching by email: {email}")
        params = {
            'email': email,
            'house_value': str(include_house_value).lower(),
            'extra_info': str(include_extra_info).lower()
        }
        result = self._make_request(params)
        if self.config.debug_mode:
            logger.debug(f"Email search result: {result}")
        
        if isinstance(result, dict) and 'error' in result:
            return EmailSearchResult(email=email)
        elif isinstance(result, list) and len(result) == 0:
            return EmailSearchResult(email=email)
        elif not result:
            return EmailSearchResult(email=email)
            
        if isinstance(result, list):
            if len(result) > 0:
                result = result[0]
            else:
                return EmailSearchResult(email=email)
        
        return EmailSearchResult(
            email=email,
            name=result.get('name'),
            dob=result.get('dob'),
            addresses=[self._parse_address(addr) for addr in result.get('addresses', [])],
            phone_numbers=[self._parse_phone_number(num, phone_format) for num in result.get('numbers', [])],
            age=result.get('age')
        )

    def search_phone(self, phone: str, include_house_value: bool = False, include_extra_info: bool = False, phone_format: str = "international") -> List[PhoneSearchResult]:
        if self.config.debug_mode:
            logger.debug(f"Searching by phone: {phone}")
        params = {
            'phone': phone,
            'house_value': str(include_house_value).lower(),
            'extra_info': str(include_extra_info).lower()
        }
        result = self._make_request(params)
        if self.config.debug_mode:
            logger.debug(f"Phone search result: {result}")
        
        if isinstance(result, dict) and 'error' in result:
            return [PhoneSearchResult(phone=self._parse_phone_number(phone, phone_format))]
        elif isinstance(result, list) and len(result) == 0:
            return [PhoneSearchResult(phone=self._parse_phone_number(phone, phone_format))]
        elif not result:
            return [PhoneSearchResult(phone=self._parse_phone_number(phone, phone_format))]
            
        if isinstance(result, dict):
            result = [result]
        
        phone_results = []
        for item in result:
            if isinstance(item, dict):
                phone_results.append(PhoneSearchResult(
                    phone=self._parse_phone_number(phone, phone_format),
                    name=item.get('name') if item.get('name') else None,
                    dob=item.get('dob'),
                    addresses=[self._parse_address(addr) for addr in item.get('addresses', [])],
                    phone_numbers=[self._parse_phone_number(num, phone_format) for num in item.get('numbers', [])],
                    emails=item.get('emails', []),
                    age=item.get('age')
                ))
        
        if not phone_results:
            phone_results = [PhoneSearchResult(phone=self._parse_phone_number(phone, phone_format))]
            
        return phone_results

    def search_domain(self, domain: str) -> DomainSearchResult:
        if self.config.debug_mode:
            logger.debug(f"Searching by domain: {domain}")
        params = {'domain': domain}
        result = self._make_request(params)
        if self.config.debug_mode:
            logger.debug(f"Domain search result: {result}")
        
        if isinstance(result, dict) and 'error' in result:
            return DomainSearchResult(domain=domain)
        elif not isinstance(result, list):
            return DomainSearchResult(domain=domain)
            
        email_results = []
        for item in result:
            if isinstance(item, dict):
                email_results.append(EmailSearchResult(
                    email=item.get('email', ''),
                    name=item.get('name'),
                    dob=item.get('dob'),
                    addresses=[self._parse_address(addr) for addr in item.get('addresses', [])],
                    phone_numbers=[self._parse_phone_number(num) for num in item.get('numbers', [])],
                    age=item.get('age')
                ))
            
        return DomainSearchResult(
            domain=domain,
            results=email_results,
            total_results=len(email_results)
        )
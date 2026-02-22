import json
import os
import sys
import traceback
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from search_api import SearchAPI, SearchAPIConfig
from search_api.exceptions import (
    SearchAPIError, AuthenticationError, ValidationError, RateLimitError,
    InsufficientBalanceError, ServerError, NetworkError, TimeoutError
)

# Config file path (same directory as this script) - persisted across runs
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'search_api_config.json')

# =============================================================================
# USER CONFIGURATION - CUSTOMIZE THESE SETTINGS (or use interactive setup)
# =============================================================================
# On first run (or with --configure / -c), the script will prompt for options,
# output fields, and (if recovery is enabled) which recovery modules to use and
# in what order. Settings are saved to search_api_config.json in this directory.
# =============================================================================

# API Configuration
api_key = ""  # Set here or via interactive setup; stored in search_api_config.json

# Search Options (overwritten by load_config() if config exists)
HOUSE_VALUE = True            # Include property value information (Zestimate) (+$0.0015)
OUTPUT_ALL = False            # Output all results, even empty ones
EXTRA_INFO = False            # Include additional data enrichment (+$0.0015)
CARRIER_INFO = False          # Include carrier information (+$0.0005)
TLO_ENRICHMENT = True         # Include TLO enrichment data (+$0.0025)
RECOVERY_CHECK = False        # Phone recovery verification for email (variable cost per module)
RECOVERY_MODULES = None       # {"module_order": [...], "enabled_modules": [...]} when recovery enabled

# Performance Settings
MAX_WORKERS = 20               # Number of concurrent workers
MAX_RETRIES = 3                # Maximum retry attempts
RETRY_DELAY_BASE = 1           # Reduced delay base for faster retries

# Connection Pool Settings
CONNECTION_POOL_MAXSIZE = MAX_WORKERS * 2

# OUTPUT FIELD CONFIGURATION
# Set to True to include each field in the output, False to exclude it
# Note: TLO-only fields will be automatically disabled if TLO_ENRICHMENT is False
OUTPUT_FIELDS_BASE = {
    'email': True,             # The searched email address
    'name': True,              # Person's full name
    'dob': True,               # Date of birth
    'age': True,               # Person's age
    'gender': False,           # Person's gender (extra_info)
    'phone_numbers': True,     # All associated phone numbers
    'addresses': True,         # All addresses
    'addresses_structured': True, # Structured addresses with components
    'emails': False,           # Additional email addresses found
    'other_emails': False,     # Other email addresses (TLO-only)
    'email_valid': False,      # Whether the email is valid
    'email_type': False,       # Type of email (personal, business, etc.)
    'total_results': False,    # Number of results found
    'search_cost': False,      # Total cost of the search in USD
    'pricing_breakdown': False, # Detailed pricing breakdown
    # Extra-info enrichment (when EXTRA_INFO=True)
    'location_metro': False,
    'companies': False,        # Company name + position
    'industry': False,
    'linkedin_url': False,
    'linkedin_id': False,
    'social_media_identifiers': False,
    'education': False,
    # Recovery check (when RECOVERY_CHECK=True)
    'recovery_check': False,   # matched, matched_number, modules_used
    # TLO Enrichment Fields (when TLO_ENRICHMENT=True)
    'censored_numbers': True,
    'alternative_names': True,
    'all_names': True,
    'all_dobs': True,
    'related_persons': False,
    'criminal_records': True,
    'phone_numbers_full': True,
    'confirmed_numbers': True,
}

# TLO-only fields that should be disabled when TLO_ENRICHMENT is False
TLO_ONLY_FIELDS = [
    'censored_numbers',
    'alternative_names',
    'all_names',
    'all_dobs',
    'related_persons',
    'criminal_records',
    'phone_numbers_full',
    'confirmed_numbers',
    'other_emails',
]

# Build OUTPUT_FIELDS based on TLO_ENRICHMENT setting
OUTPUT_FIELDS = OUTPUT_FIELDS_BASE.copy()
if not TLO_ENRICHMENT:
    # Disable TLO-only fields when TLO enrichment is not enabled
    for field in TLO_ONLY_FIELDS:
        OUTPUT_FIELDS[field] = False

# OUTPUT FORMAT CONFIGURATION (overwritten by config / interactive setup)
OUTPUT_FORMAT = 'text'         # 'text' | 'csv' | 'json'
OUTPUT_SEPARATOR = ' | '       # Separator for text format
OUTPUT_CSV_DELIMITER = ','     # Delimiter for CSV (e.g. ',', '\t', ';', '|')
OUTPUT_ENCODING = 'UTF-8'      # File encoding for output
INCLUDE_HEADER = True          # Include header row in output file

# ADDRESS FORMAT CONFIGURATION
ADDRESS_INCLUDE_PROPERTY_DETAILS = True    # Include bedrooms, bathrooms, etc.
ADDRESS_INCLUDE_ZESTIMATE = True           # Include property value (requires HOUSE_VALUE=True)
ADDRESS_INCLUDE_STATUS = True              # Include home status
ADDRESS_INCLUDE_LAST_KNOWN = False         # Include last known date


# =============================================================================
# PERSISTENT CONFIG: load / save / interactive setup
# =============================================================================

def _get_field_list_for_prompt(include_tlo_fields: bool = True) -> List[str]:
    """Ordered list of field keys for numbered prompts. Excludes TLO-only fields when include_tlo_fields is False."""
    all_fields = [
        'email', 'name', 'dob', 'age', 'gender', 'phone_numbers', 'addresses',
        'addresses_structured', 'emails', 'other_emails', 'email_valid', 'email_type',
        'total_results', 'search_cost', 'pricing_breakdown', 'location_metro',
        'companies', 'industry', 'linkedin_url', 'linkedin_id', 'social_media_identifiers',
        'education', 'recovery_check', 'censored_numbers', 'alternative_names',
        'all_names', 'all_dobs', 'related_persons', 'criminal_records',
        'phone_numbers_full', 'confirmed_numbers',
    ]
    if include_tlo_fields:
        return all_fields
    return [k for k in all_fields if k not in TLO_ONLY_FIELDS]


def _yes_no(prompt: str, default: bool) -> bool:
    """Prompt for y/n; return True for y/yes, False for n/no."""
    d = 'Y' if default else 'N'
    while True:
        raw = input(f"  {prompt} (y/n) [{d}]: ").strip().lower()
        if not raw:
            return default
        if raw in ('y', 'yes'):
            return True
        if raw in ('n', 'no'):
            return False
        print("  Enter y or n.")


def load_config() -> bool:
    """Load config from CONFIG_PATH into module globals. Returns True if loaded."""
    global api_key, HOUSE_VALUE, OUTPUT_ALL, EXTRA_INFO, CARRIER_INFO
    global TLO_ENRICHMENT, RECOVERY_CHECK, RECOVERY_MODULES, OUTPUT_FIELDS
    global OUTPUT_FORMAT, OUTPUT_SEPARATOR, OUTPUT_CSV_DELIMITER
    if not os.path.isfile(CONFIG_PATH):
        return False
    try:
        with open(CONFIG_PATH, 'r', encoding='UTF-8') as f:
            data = json.load(f)
        api_key = data.get('api_key', api_key)
        HOUSE_VALUE = data.get('house_value', HOUSE_VALUE)
        OUTPUT_ALL = data.get('output_all', OUTPUT_ALL)
        EXTRA_INFO = data.get('extra_info', EXTRA_INFO)
        CARRIER_INFO = data.get('carrier_info', CARRIER_INFO)
        TLO_ENRICHMENT = data.get('tlo_enrichment', TLO_ENRICHMENT)
        RECOVERY_CHECK = data.get('recovery_check', RECOVERY_CHECK)
        RECOVERY_MODULES = data.get('recovery_modules')
        OUTPUT_FORMAT = data.get('output_format', OUTPUT_FORMAT)
        OUTPUT_SEPARATOR = data.get('output_separator', OUTPUT_SEPARATOR)
        OUTPUT_CSV_DELIMITER = data.get('output_csv_delimiter', OUTPUT_CSV_DELIMITER)
        out = data.get('output_fields')
        if isinstance(out, dict):
            OUTPUT_FIELDS.clear()
            OUTPUT_FIELDS.update(OUTPUT_FIELDS_BASE)
            OUTPUT_FIELDS.update(out)
            if not TLO_ENRICHMENT:
                for f in TLO_ONLY_FIELDS:
                    OUTPUT_FIELDS[f] = False
        return True
    except Exception as e:
        logging.warning(f"Could not load config from {CONFIG_PATH}: {e}")
        return False


def save_config() -> None:
    """Save current options and output fields to CONFIG_PATH."""
    data = {
        'api_key': api_key,
        'house_value': HOUSE_VALUE,
        'output_all': OUTPUT_ALL,
        'extra_info': EXTRA_INFO,
        'carrier_info': CARRIER_INFO,
        'tlo_enrichment': TLO_ENRICHMENT,
        'recovery_check': RECOVERY_CHECK,
        'recovery_modules': RECOVERY_MODULES,
        'output_format': OUTPUT_FORMAT,
        'output_separator': OUTPUT_SEPARATOR,
        'output_csv_delimiter': OUTPUT_CSV_DELIMITER,
        'output_fields': dict(OUTPUT_FIELDS),
    }
    with open(CONFIG_PATH, 'w', encoding='UTF-8') as f:
        json.dump(data, f, indent=2)
    print(f"  Configuration saved to {CONFIG_PATH}")


def interactive_setup() -> None:
    """Prompt for options, fields, and (if recovery enabled) recovery modules; then save."""
    global api_key, HOUSE_VALUE, EXTRA_INFO, CARRIER_INFO, TLO_ENRICHMENT, RECOVERY_CHECK
    global RECOVERY_MODULES, OUTPUT_FIELDS, OUTPUT_FORMAT, OUTPUT_SEPARATOR, OUTPUT_CSV_DELIMITER, OUTPUT_ALL

    print("\n=== Search API – Interactive configuration ===\n")

    # API key
    if not api_key:
        api_key_in = input("Enter your API key: ").strip()
        if not api_key_in:
            print("API key is required. Exiting.")
            sys.exit(1)
        api_key = api_key_in
    else:
        change = input(f"Use existing API key? (y/n) [y]: ").strip().lower()
        if change in ('n', 'no'):
            api_key = input("Enter your API key: ").strip() or api_key

    # Search options
    print("\n--- Search options ---")
    HOUSE_VALUE = _yes_no("House value (Zestimate) (+$0.0015)", False)
    EXTRA_INFO = _yes_no("Extra info enrichment (+$0.0015)", False)
    CARRIER_INFO = _yes_no("Carrier info (+$0.0005)", False)
    TLO_ENRICHMENT = _yes_no("TLO enrichment (+$0.0025)", False)
    RECOVERY_CHECK = _yes_no("Phone recovery verification (variable cost per module)", False)

    # Recovery modules (if recovery enabled)
    RECOVERY_MODULES = None
    if RECOVERY_CHECK:
        print("\n--- Recovery modules ---")
        print("  Fetching available modules...")
        try:
            config = SearchAPIConfig(api_key=api_key, debug_mode=False)
            client = SearchAPI(config=config)
            recovery = client.get_recovery_modules()
            client.close()
        except Exception as e:
            print(f"  Could not fetch recovery modules: {e}. You can set recovery modules later in the config file.")
        else:
            modules = recovery.modules
            if not modules:
                print("  No recovery modules returned by API.")
            else:
                for i, m in enumerate(modules, 1):
                    price = recovery.pricing.get(m.module_name, m.price)
                    print(f"    {i}. {m.module_name}  (${price:.4f})")
                print("  Enter the numbers of modules to ENABLE and their RUN ORDER (comma-separated, e.g. 1,3,4):")
                en_str = input("  Enabled + order: ").strip()
                if en_str:
                    try:
                        indices = [int(x.strip()) for x in en_str.split(",") if x.strip()]
                        enabled = [modules[i - 1].module_name for i in indices if 1 <= i <= len(modules)]
                    except (ValueError, IndexError):
                        enabled = [m.module_name for m in modules]
                    else:
                        if not enabled:
                            enabled = [m.module_name for m in modules]
                    RECOVERY_MODULES = {"module_order": enabled, "enabled_modules": enabled}
                    print(f"  Using: {enabled}")

    # Output fields (only show TLO enrichment fields if TLO was enabled)
    print("\n--- Output fields ---")
    field_list = _get_field_list_for_prompt(include_tlo_fields=TLO_ENRICHMENT)
    for i, key in enumerate(field_list, 1):
        current = OUTPUT_FIELDS.get(key, False)
        print(f"  {i:2}. {key}  [{'on' if current else 'off'}]")
    print("  Enter field numbers to INCLUDE (comma or range, e.g. 1,2,3,5-8), 'all', or 'default':")
    choice = input("  Fields: ").strip().lower()
    if choice == 'all':
        for k in field_list:
            OUTPUT_FIELDS[k] = True
    elif choice == 'default':
        # sensible default: email, name, dob, age, phone_numbers, addresses, key TLO fields
        default_on = {'email', 'name', 'dob', 'age', 'phone_numbers', 'addresses', 'addresses_structured',
                     'censored_numbers', 'alternative_names', 'all_names', 'all_dobs', 'phone_numbers_full', 'confirmed_numbers'}
        for k in field_list:
            OUTPUT_FIELDS[k] = k in default_on
    elif choice:
        try:
            included = set()
            for part in choice.split(","):
                part = part.strip()
                if "-" in part:
                    a, b = part.split("-", 1)
                    lo, hi = int(a.strip()), int(b.strip())
                    for idx in range(lo, hi + 1):
                        if 1 <= idx <= len(field_list):
                            included.add(field_list[idx - 1])
                else:
                    idx = int(part)
                    if 1 <= idx <= len(field_list):
                        included.add(field_list[idx - 1])
            for k in field_list:
                OUTPUT_FIELDS[k] = k in included
        except ValueError:
            print("  Invalid input; keeping current field selection.")

    if not TLO_ENRICHMENT:
        for f in TLO_ONLY_FIELDS:
            OUTPUT_FIELDS[f] = False

    # Output format and options
    print("\n--- Output format ---")
    print("  1. Text (pipe-separated)")
    print("  2. CSV")
    print("  3. JSON (one object per line)")
    fmt = input("  Output format (1–3) [1]: ").strip() or "1"
    if fmt == "2":
        OUTPUT_FORMAT = "csv"
        print("  CSV delimiter: 1=comma, 2=tab, 3=semicolon, 4=pipe, 5=custom")
        delim = input("  Delimiter (1–5) [1]: ").strip() or "1"
        if delim == "2":
            OUTPUT_CSV_DELIMITER = "\t"
        elif delim == "3":
            OUTPUT_CSV_DELIMITER = ";"
        elif delim == "4":
            OUTPUT_CSV_DELIMITER = "|"
        elif delim == "5":
            custom = input("  Enter delimiter character: ").strip()
            if custom:
                OUTPUT_CSV_DELIMITER = custom
        else:
            OUTPUT_CSV_DELIMITER = ","
    elif fmt == "3":
        OUTPUT_FORMAT = "json"
    else:
        OUTPUT_FORMAT = "text"
        OUTPUT_SEPARATOR = " | "

    print("  Output only emails that were found (recommended), or all lines (including not found)?")
    OUTPUT_ALL = _yes_no("  Output all lines (including not found)", default=False)

    save_config()
    print("\nConfiguration complete. Run the script again (without --configure) to process emails.\n")


# =============================================================================
# END USER CONFIGURATION
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('search_api.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def get_output_field_order() -> List[str]:
    """Get the order of fields to output based on configuration."""
    return [field for field, enabled in OUTPUT_FIELDS.items() if enabled]


def get_output_separator() -> str:
    """Return the separator for the current output format (CSV delimiter or text separator)."""
    return OUTPUT_CSV_DELIMITER if OUTPUT_FORMAT == 'csv' else OUTPUT_SEPARATOR


def _csv_quote_field(value: str, delimiter: str) -> str:
    """Quote a CSV field if it contains the delimiter, newline, or double-quote."""
    if delimiter in value or '\n' in value or '\r' in value or '"' in value:
        return '"' + value.replace('"', '""') + '"'
    return value


def create_header() -> str:
    """Create header row based on enabled fields."""
    if not INCLUDE_HEADER:
        return ""
    
    field_names = {
        'email': 'Email',
        'name': 'Name',
        'dob': 'DOB',
        'age': 'Age',
        'gender': 'Gender',
        'phone_numbers': 'Phone Numbers',
        'addresses': 'Addresses',
        'emails': 'Emails',
        'other_emails': 'Other Emails',
        'email_valid': 'Email Valid',
        'email_type': 'Email Type',
        'total_results': 'Total Results',
        'search_cost': 'Search Cost',
        'pricing_breakdown': 'Pricing Breakdown',
        'location_metro': 'Location Metro',
        'companies': 'Companies',
        'industry': 'Industry',
        'linkedin_url': 'LinkedIn URL',
        'linkedin_id': 'LinkedIn ID',
        'social_media_identifiers': 'Social Media',
        'education': 'Education',
        'recovery_check': 'Recovery Check',
        'censored_numbers': 'Censored Numbers',
        'alternative_names': 'Alternative Names',
        'all_names': 'All Names',
        'all_dobs': 'All DOBs',
        'related_persons': 'Related Persons',
        'criminal_records': 'Criminal Records',
        'phone_numbers_full': 'Phone Numbers Full',
        'confirmed_numbers': 'Confirmed Numbers',
        'addresses_structured': 'Structured Addresses',
    }
    
    enabled_fields = get_output_field_order()
    header_fields = [field_names[field] for field in enabled_fields]
    sep = get_output_separator()
    if OUTPUT_FORMAT == 'csv':
        return sep.join(_csv_quote_field(h, sep) for h in header_fields)
    return sep.join(header_fields)


def load_emails(file_path: str) -> List[str]:
    """Load emails from file with proper error handling."""
    try:
        with open(file_path, 'r', encoding="UTF-8") as f:
            emails = [line.strip() for line in f if line.strip()]
        
        valid_emails = []
        for email in emails:
            if '@' in email and '.' in email.split('@')[1]:
                valid_emails.append(email)
            else:
                logger.warning(f"Invalid email format: {email}")
        
        logger.info(f"Loaded {len(valid_emails)} valid emails from {file_path}")
        return valid_emails
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
        raise
    except Exception as e:
        logger.error(f"Error loading emails from {file_path}: {str(e)}")
        raise


def format_address(addr) -> str:
    """Format address with configurable fields."""
    if not addr:
        return 'N/A'
    
    address_parts = []
    
    if hasattr(addr, 'street') and addr.street:
        address_parts.append(addr.street)
    if hasattr(addr, 'city') and addr.city:
        address_parts.append(addr.city)
    if hasattr(addr, 'state') and addr.state:
        address_parts.append(addr.state)
    if hasattr(addr, 'postal_code') and addr.postal_code:
        address_parts.append(addr.postal_code)
    if hasattr(addr, 'country') and addr.country:
        address_parts.append(addr.country)
    
    address_str = ', '.join(address_parts) if address_parts else 'N/A'
    
    if ADDRESS_INCLUDE_PROPERTY_DETAILS:
        property_details = []
        
        if ADDRESS_INCLUDE_ZESTIMATE and HOUSE_VALUE and hasattr(addr, 'zestimate') and addr.zestimate:
            property_details.append(f"Zestimate: ${addr.zestimate:,.2f}")
        
        if hasattr(addr, 'bedrooms') and addr.bedrooms:
            property_details.append(f"{addr.bedrooms} beds")
        if hasattr(addr, 'bathrooms') and addr.bathrooms:
            property_details.append(f"{addr.bathrooms} baths")
        if hasattr(addr, 'living_area') and addr.living_area:
            property_details.append(f"{addr.living_area} sqft")
        
        if ADDRESS_INCLUDE_STATUS and hasattr(addr, 'home_status') and addr.home_status:
            property_details.append(f"Status: {addr.home_status}")
        
        if ADDRESS_INCLUDE_LAST_KNOWN and hasattr(addr, 'last_known_date') and addr.last_known_date:
            property_details.append(f"Last known: {addr.last_known_date}")
        
        if property_details:
            address_str += f" ({', '.join(property_details)})"
    
    return address_str


def format_phone_numbers(phone_numbers: List) -> str:
    """Format phone numbers with all available details."""
    if not phone_numbers:
        return 'None' if OUTPUT_ALL else 'N/A'
    
    phone_strs = []
    for phone in phone_numbers:
        if not phone:
            continue
            
        phone_info = []
        if hasattr(phone, 'number') and phone.number:
            phone_info.append(phone.number)
        else:
            phone_info.append(str(phone))
        
        if hasattr(phone, 'carrier') and phone.carrier:
            phone_info.append(f"({phone.carrier})")
        
        phone_strs.append(' '.join(phone_info))
    
    return '; '.join(phone_strs) if phone_strs else ('None' if OUTPUT_ALL else 'N/A')


def format_phone_numbers_full(phone_numbers_full: List) -> str:
    """Format full phone number details with carrier and metadata."""
    if not phone_numbers_full:
        return 'None' if OUTPUT_ALL else 'N/A'
    
    phone_strs = []
    for phone in phone_numbers_full:
        if not phone or not hasattr(phone, 'number'):
            continue
        
        info_parts = [phone.number]
        if hasattr(phone, 'line_type') and phone.line_type:
            info_parts.append(phone.line_type)
        if hasattr(phone, 'carrier') and phone.carrier:
            info_parts.append(f"Carrier: {phone.carrier}")
        if hasattr(phone, 'is_spam_report') and phone.is_spam_report is not None:
            info_parts.append(f"Spam: {phone.is_spam_report}")
        
        phone_strs.append(' | '.join(info_parts))
    
    return '; '.join(phone_strs) if phone_strs else ('None' if OUTPUT_ALL else 'N/A')


def format_censored_numbers(censored_numbers: List[str]) -> str:
    """Format censored phone numbers."""
    if not censored_numbers:
        return 'None' if OUTPUT_ALL else 'N/A'
    
    return '; '.join(censored_numbers)


def format_alternative_names(alternative_names: List[str]) -> str:
    """Format alternative names."""
    if not alternative_names:
        return 'None' if OUTPUT_ALL else 'N/A'
    
    return '; '.join(alternative_names)


def format_all_names(all_names: List) -> str:
    """Format all name records with dates."""
    if not all_names:
        return 'None' if OUTPUT_ALL else 'N/A'
    
    name_strs = []
    for name_record in all_names:
        if not name_record or not hasattr(name_record, 'name'):
            continue
        
        info_parts = [name_record.name]
        if hasattr(name_record, 'first') and name_record.first:
            parts = [name_record.first]
            if hasattr(name_record, 'middle') and name_record.middle:
                parts.append(name_record.middle)
            if hasattr(name_record, 'last') and name_record.last:
                parts.append(name_record.last)
            info_parts.append(f"({' '.join(parts)})")
        
        name_strs.append(' '.join(info_parts))
    
    return '; '.join(name_strs) if name_strs else ('None' if OUTPUT_ALL else 'N/A')


def format_all_dobs(all_dobs: List) -> str:
    """Format all date of birth records."""
    if not all_dobs:
        return 'None' if OUTPUT_ALL else 'N/A'
    
    dob_strs = []
    for dob_record in all_dobs:
        if not dob_record or not hasattr(dob_record, 'dob'):
            continue
        
        info = dob_record.dob
        if hasattr(dob_record, 'age') and dob_record.age:
            info += f" (Age: {dob_record.age})"
        
        dob_strs.append(info)
    
    return '; '.join(dob_strs) if dob_strs else ('None' if OUTPUT_ALL else 'N/A')


def format_related_persons(related_persons: List) -> str:
    """Format related persons."""
    if not related_persons:
        return 'None' if OUTPUT_ALL else 'N/A'
    
    person_strs = []
    for person in related_persons:
        if not person or not hasattr(person, 'name'):
            continue
        
        info_parts = [person.name]
        if hasattr(person, 'relationship') and person.relationship:
            info_parts.append(f"({person.relationship})")
        if hasattr(person, 'age') and person.age:
            info_parts.append(f"Age: {person.age}")
        
        person_strs.append(' '.join(info_parts))
    
    return '; '.join(person_strs) if person_strs else ('None' if OUTPUT_ALL else 'N/A')


def format_criminal_records(criminal_records: List) -> str:
    """Format criminal records."""
    if not criminal_records:
        return 'None' if OUTPUT_ALL else 'N/A'
    
    record_strs = []
    for record in criminal_records:
        if not record or not hasattr(record, 'source_name'):
            continue
        
        info_parts = [record.source_name]
        if hasattr(record, 'source_state') and record.source_state:
            info_parts.append(f"({record.source_state})")
        if hasattr(record, 'crimes') and record.crimes:
            crime_types = []
            for crime in record.crimes:
                if hasattr(crime, 'crime_type') and crime.crime_type:
                    crime_types.append(crime.crime_type)
            if crime_types:
                info_parts.append(f"Types: {', '.join(set(crime_types))}")
        
        record_strs.append(' | '.join(info_parts))
    
    return '; '.join(record_strs) if record_strs else ('None' if OUTPUT_ALL else 'N/A')


def format_addresses_structured(addresses_structured: List) -> str:
    """Format structured addresses with components."""
    if not addresses_structured:
        return 'None' if OUTPUT_ALL else 'N/A'
    
    addr_strs = []
    for addr in addresses_structured:
        if not addr or not hasattr(addr, 'address'):
            continue
        
        info_parts = [addr.address]
        if hasattr(addr, 'components') and addr.components:
            comp = addr.components
            comp_parts = []
            if comp.city:
                comp_parts.append(comp.city)
            if comp.state_code:
                comp_parts.append(comp.state_code)
            if comp.zip_code:
                comp_parts.append(comp.zip_code)
            if comp.county:
                comp_parts.append(f"County: {comp.county}")
            if comp_parts:
                info_parts.append(f"({', '.join(comp_parts)})")
        
        addr_strs.append(' '.join(info_parts))
    
    return '; '.join(addr_strs) if addr_strs else ('None' if OUTPUT_ALL else 'N/A')


def format_pricing_breakdown(pricing) -> str:
    """Format pricing breakdown."""
    if not pricing:
        return 'N/A'
    
    parts = []
    if hasattr(pricing, 'search_cost') and pricing.search_cost:
        parts.append(f"Base: ${pricing.search_cost:.4f}")
    if hasattr(pricing, 'extra_info_cost') and pricing.extra_info_cost:
        parts.append(f"Extra: ${pricing.extra_info_cost:.4f}")
    if hasattr(pricing, 'zestimate_cost') and pricing.zestimate_cost:
        parts.append(f"Zestimate: ${pricing.zestimate_cost:.4f}")
    if hasattr(pricing, 'carrier_cost') and pricing.carrier_cost:
        parts.append(f"Carrier: ${pricing.carrier_cost:.4f}")
    if hasattr(pricing, 'tlo_enrichment_cost') and pricing.tlo_enrichment_cost:
        parts.append(f"TLO: ${pricing.tlo_enrichment_cost:.4f}")
    if hasattr(pricing, 'recovery_check_cost') and pricing.recovery_check_cost:
        parts.append(f"Recovery: ${pricing.recovery_check_cost:.4f}")
    if hasattr(pricing, 'total_cost') and pricing.total_cost:
        parts.append(f"Total: ${pricing.total_cost:.4f}")
    
    return ' | '.join(parts) if parts else 'N/A'


def format_addresses(addresses: List) -> str:
    """Format addresses with configurable fields."""
    if not addresses:
        return 'None' if OUTPUT_ALL else 'N/A'
    
    address_strs = []
    for addr in addresses:
        formatted_addr = format_address(addr)
        if formatted_addr and formatted_addr != 'N/A':
            address_strs.append(formatted_addr)
    
    return '; '.join(address_strs) if address_strs else ('None' if OUTPUT_ALL else 'N/A')


def format_person(person) -> Dict[str, str]:
    """Format person information with configurable fields."""
    if not person:
        return {
            'name': 'None' if OUTPUT_ALL else 'N/A',
            'dob': 'None' if OUTPUT_ALL else 'N/A',
            'age': 'None' if OUTPUT_ALL else 'N/A',
            'gender': 'None' if OUTPUT_ALL else 'N/A'
        }
    
    name = 'N/A'
    dob = 'N/A'
    age = 'N/A'
    gender = 'N/A'
    
    if hasattr(person, 'name') and person.name:
        name = person.name
    elif OUTPUT_ALL:
        name = 'None'
    
    if hasattr(person, 'dob') and person.dob:
        dob = str(person.dob)
    elif OUTPUT_ALL:
        dob = 'None'
    
    if hasattr(person, 'age') and person.age:
        age = str(person.age)
    elif OUTPUT_ALL:
        age = 'None'
    
    if hasattr(person, 'gender') and person.gender:
        gender = person.gender
    elif OUTPUT_ALL:
        gender = 'None'
    
    return {'name': name, 'dob': dob, 'age': age, 'gender': gender}


def format_emails(emails: List[str]) -> str:
    """Format email list."""
    if not emails:
        return 'None' if OUTPUT_ALL else 'N/A'
    
    return '; '.join(emails)


def format_search_metadata(result) -> Dict[str, str]:
    """Format search metadata with configurable fields."""
    metadata = {}
    
    if hasattr(result, 'email'):
        metadata['email'] = result.email if result.email else 'N/A'
    if hasattr(result, 'email_valid'):
        metadata['email_valid'] = str(result.email_valid)
    if hasattr(result, 'email_type'):
        metadata['email_type'] = result.email_type if result.email_type else 'N/A'
    
    if hasattr(result, 'total_results'):
        metadata['total_results'] = str(result.total_results)
    if hasattr(result, 'search_cost'):
        metadata['search_cost'] = f"${result.search_cost:.4f}" if result.search_cost else 'N/A'
    if hasattr(result, 'pricing'):
        metadata['pricing_breakdown'] = format_pricing_breakdown(result.pricing)
    if hasattr(result, 'search_timestamp'):
        metadata['search_timestamp'] = result.search_timestamp.isoformat() if result.search_timestamp else 'N/A'
    
    # TLO Enrichment fields
    if hasattr(result, 'censored_numbers'):
        metadata['censored_numbers'] = format_censored_numbers(result.censored_numbers)
    if hasattr(result, 'alternative_names'):
        metadata['alternative_names'] = format_alternative_names(result.alternative_names)
    if hasattr(result, 'all_names'):
        metadata['all_names'] = format_all_names(result.all_names)
    if hasattr(result, 'all_dobs'):
        metadata['all_dobs'] = format_all_dobs(result.all_dobs)
    if hasattr(result, 'related_persons'):
        metadata['related_persons'] = format_related_persons(result.related_persons)
    if hasattr(result, 'criminal_records'):
        metadata['criminal_records'] = format_criminal_records(result.criminal_records)
    if hasattr(result, 'phone_numbers_full'):
        metadata['phone_numbers_full'] = format_phone_numbers_full(result.phone_numbers_full)
    if hasattr(result, 'confirmed_numbers'):
        metadata['confirmed_numbers'] = '; '.join(result.confirmed_numbers) if result.confirmed_numbers else ('None' if OUTPUT_ALL else 'N/A')
    if hasattr(result, 'addresses_structured'):
        metadata['addresses_structured'] = format_addresses_structured(result.addresses_structured)
    if hasattr(result, 'other_emails'):
        metadata['other_emails'] = format_emails(result.other_emails) if hasattr(result, 'other_emails') else ('None' if OUTPUT_ALL else 'N/A')
    # Extra-info enrichment
    if hasattr(result, 'location_metro') and result.location_metro:
        metadata['location_metro'] = result.location_metro
    if hasattr(result, 'companies') and result.companies:
        metadata['companies'] = '; '.join(f"{c.company_name}" + (f" ({c.position})" if c.position else "") for c in result.companies)
    if hasattr(result, 'industry') and result.industry:
        metadata['industry'] = result.industry
    if hasattr(result, 'linkedin_url') and result.linkedin_url:
        metadata['linkedin_url'] = result.linkedin_url
    if hasattr(result, 'linkedin_id') and result.linkedin_id:
        metadata['linkedin_id'] = result.linkedin_id
    if hasattr(result, 'social_media_identifiers') and result.social_media_identifiers:
        metadata['social_media_identifiers'] = '; '.join(f"{s.platform}:{s.identifier}" for s in result.social_media_identifiers)
    if hasattr(result, 'education') and result.education:
        metadata['education'] = '; '.join(f"{e.school_name}" + (f" ({e.start_date}-{e.end_date})" if (e.start_date or e.end_date) else "") for e in result.education)
    if hasattr(result, 'recovery_check') and result.recovery_check:
        rc = result.recovery_check
        metadata['recovery_check'] = f"matched={rc.matched} matched_number={rc.matched_number or 'N/A'} modules={','.join(rc.modules_used or [])}"
    
    return metadata


def create_output_row(result, original_email: str):
    """Build list of output values for configured fields. Returns None if no result and not OUTPUT_ALL."""
    if not result:
        if OUTPUT_ALL:
            enabled_fields = get_output_field_order()
            return ['None'] * len(enabled_fields)
        return None

    person_info = format_person(result.person)
    phone_numbers = result.phone_numbers if hasattr(result, 'phone_numbers') else []
    all_numbers = format_phone_numbers(phone_numbers)
    addresses = result.addresses if hasattr(result, 'addresses') else []
    all_addresses = format_addresses(addresses)
    emails = result.emails if hasattr(result, 'emails') else []
    all_emails = format_emails(emails)
    metadata = format_search_metadata(result)

    enabled_fields = get_output_field_order()
    output_values = []

    for field in enabled_fields:
        if field == 'email':
            output_values.append(metadata.get('email', original_email))
        elif field == 'name':
            output_values.append(person_info['name'])
        elif field == 'dob':
            output_values.append(person_info['dob'])
        elif field == 'age':
            output_values.append(person_info['age'])
        elif field == 'gender':
            output_values.append(person_info.get('gender', 'N/A'))
        elif field == 'phone_numbers':
            output_values.append(all_numbers)
        elif field == 'addresses':
            output_values.append(all_addresses)
        elif field == 'emails':
            output_values.append(all_emails)
        elif field == 'other_emails':
            output_values.append(metadata.get('other_emails', 'N/A'))
        elif field == 'email_valid':
            output_values.append(metadata.get('email_valid', 'N/A'))
        elif field == 'email_type':
            output_values.append(metadata.get('email_type', 'N/A'))
        elif field == 'total_results':
            output_values.append(metadata.get('total_results', 'N/A'))
        elif field == 'search_cost':
            output_values.append(metadata.get('search_cost', 'N/A'))
        elif field == 'pricing_breakdown':
            output_values.append(metadata.get('pricing_breakdown', 'N/A'))
        elif field == 'censored_numbers':
            output_values.append(metadata.get('censored_numbers', 'N/A'))
        elif field == 'alternative_names':
            output_values.append(metadata.get('alternative_names', 'N/A'))
        elif field == 'all_names':
            output_values.append(metadata.get('all_names', 'N/A'))
        elif field == 'all_dobs':
            output_values.append(metadata.get('all_dobs', 'N/A'))
        elif field == 'related_persons':
            output_values.append(metadata.get('related_persons', 'N/A'))
        elif field == 'criminal_records':
            output_values.append(metadata.get('criminal_records', 'N/A'))
        elif field == 'phone_numbers_full':
            output_values.append(metadata.get('phone_numbers_full', 'N/A'))
        elif field == 'confirmed_numbers':
            output_values.append(metadata.get('confirmed_numbers', 'N/A'))
        elif field == 'addresses_structured':
            output_values.append(metadata.get('addresses_structured', 'N/A'))
        elif field == 'location_metro':
            output_values.append(metadata.get('location_metro', 'N/A'))
        elif field == 'companies':
            output_values.append(metadata.get('companies', 'N/A'))
        elif field == 'industry':
            output_values.append(metadata.get('industry', 'N/A'))
        elif field == 'linkedin_url':
            output_values.append(metadata.get('linkedin_url', 'N/A'))
        elif field == 'linkedin_id':
            output_values.append(metadata.get('linkedin_id', 'N/A'))
        elif field == 'social_media_identifiers':
            output_values.append(metadata.get('social_media_identifiers', 'N/A'))
        elif field == 'education':
            output_values.append(metadata.get('education', 'N/A'))
        elif field == 'recovery_check':
            output_values.append(metadata.get('recovery_check', 'N/A'))
        else:
            output_values.append('N/A')

    return output_values


def create_output_line(result, original_email: str):
    """Create a formatted output line (text or CSV). Returns None if no result and not OUTPUT_ALL."""
    row = create_output_row(result, original_email)
    if row is None:
        return None
    sep = get_output_separator()
    if OUTPUT_FORMAT == 'csv':
        return sep.join(_csv_quote_field(str(v), sep) for v in row)
    return sep.join(row)


def create_output_dict(result, original_email: str):
    """Create a dict of field -> value for JSON output. Returns None if no result and not OUTPUT_ALL."""
    row = create_output_row(result, original_email)
    if row is None:
        return None
    return dict(zip(get_output_field_order(), row))


def write_result_record(f, result, email: str) -> None:
    """Write one result record (or empty record when OUTPUT_ALL and result is None). No-op if result is None and not OUTPUT_ALL."""
    if OUTPUT_FORMAT == 'json':
        obj = create_output_dict(result, email)
        if obj is not None:
            f.write(json.dumps(obj, ensure_ascii=False) + '\n')
    else:
        line = create_output_line(result, email)
        if line is not None:
            f.write(line + '\n')


def write_error_record(f, error_line: str) -> None:
    """Write one error line. error_line is the text/csv line; for JSON we parse and write {'email': ..., 'error': ...}."""
    if OUTPUT_FORMAT == 'json':
        parts = error_line.split(' | ERROR: ', 1)
        email = parts[0].strip()
        err = parts[1].strip() if len(parts) > 1 else error_line
        f.write(json.dumps({'email': email, 'error': err}, ensure_ascii=False) + '\n')
    else:
        f.write(error_line + '\n')


def handle_api_error(error: Exception, email: str) -> str:
    """Handle different types of API errors and return appropriate error message."""
    if isinstance(error, AuthenticationError):
        logger.error(f"Authentication failed for {email}: {error}")
        return f"{email} | ERROR: Authentication failed - Invalid API key"
    
    elif isinstance(error, InsufficientBalanceError):
        logger.error(f"Insufficient balance for {email}: {error}")
        return f"{email} | ERROR: Insufficient balance - {error.current_balance if hasattr(error, 'current_balance') else 'Unknown'}"
    
    elif isinstance(error, RateLimitError):
        logger.warning(f"Rate limit exceeded for {email}: {error}")
        return f"{email} | ERROR: Rate limit exceeded - Please wait before retrying"
    
    elif isinstance(error, ValidationError):
        logger.warning(f"Validation error for {email}: {error}")
        return f"{email} | ERROR: Invalid email format"
    
    elif isinstance(error, TimeoutError):
        logger.warning(f"Timeout for {email}: {error}")
        return f"{email} | ERROR: Request timeout"
    
    elif isinstance(error, NetworkError):
        logger.warning(f"Network error for {email}: {error}")
        return f"{email} | ERROR: Network connection error"
    
    elif isinstance(error, ServerError):
        logger.error(f"Server error for {email}: {error}")
        return f"{email} | ERROR: Server error - {error.status_code if hasattr(error, 'status_code') else 'Unknown'}"
    
    else:
        logger.error(f"Unexpected error for {email}: {error}")
        return f"{email} | ERROR: Unexpected error - {str(error)}"


def optimize_existing_session(session: 'Session') -> 'Session':
    """Optimize an existing session with better connection pool settings."""
    from requests.adapters import HTTPAdapter
    from urllib3.util import Retry
    
    adapter = HTTPAdapter(
        pool_connections=10,
        pool_maxsize=CONNECTION_POOL_MAXSIZE,
        pool_block=False,
        max_retries=Retry(
            total=1,
            status_forcelist=[500, 502, 503, 504],
            backoff_factor=0.1
        )
    )
    
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    
    session.timeout = 15
    
    return session


def fetch_email_info(email: str, output_file: str, api_client: SearchAPI) -> None:
    """Fetch email information with comprehensive error handling and retries."""
    for attempt in range(MAX_RETRIES):
        try:
            logger.debug(f"Searching for email: {email} (attempt {attempt + 1})")
            
            result = api_client.search_email(
                email=email,
                phone_format="international",
                house_value=HOUSE_VALUE,
                extra_info=EXTRA_INFO,
                carrier_info=CARRIER_INFO,
                tlo_enrichment=TLO_ENRICHMENT,
                recovery_check=RECOVERY_CHECK,
                recovery_modules=RECOVERY_MODULES,
            )
            #print(result)
            
            if not result:
                if OUTPUT_ALL:
                    with open(output_file, 'a', encoding=OUTPUT_ENCODING) as f:
                        write_result_record(f, None, email)
                    logger.debug(f"No result object for: {email}")
                return
            
            has_any_data = False
            
            if (hasattr(result, 'phone_numbers') and result.phone_numbers) or \
               (hasattr(result, 'addresses') and result.addresses) or \
               (hasattr(result, 'person') and result.person and result.person.name) or \
               (hasattr(result, 'emails') and result.emails):
                has_any_data = True
            
            if (EXTRA_INFO or TLO_ENRICHMENT) and not has_any_data:
                if (hasattr(result, 'phone_numbers_full') and result.phone_numbers_full) or \
                   (hasattr(result, 'addresses_structured') and result.addresses_structured) or \
                   (hasattr(result, 'all_names') and result.all_names) or \
                   (hasattr(result, 'alternative_names') and result.alternative_names) or \
                   (hasattr(result, 'all_dobs') and result.all_dobs) or \
                   (hasattr(result, 'related_persons') and result.related_persons) or \
                   (hasattr(result, 'criminal_records') and result.criminal_records) or \
                   (hasattr(result, 'censored_numbers') and result.censored_numbers) or \
                   (hasattr(result, 'confirmed_numbers') and result.confirmed_numbers) or \
                   (hasattr(result, 'other_emails') and result.other_emails) or \
                   (hasattr(result, 'companies') and result.companies) or \
                   (hasattr(result, 'education') and result.education) or \
                   (hasattr(result, 'social_media_identifiers') and result.social_media_identifiers) or \
                   (hasattr(result, 'location_metro') and result.location_metro) or \
                   (hasattr(result, 'recovery_check') and result.recovery_check):
                    has_any_data = True
            
            if not has_any_data and hasattr(result, 'total_results') and result.total_results > 0:
                has_any_data = True
            
            if not has_any_data and not OUTPUT_ALL:
                logger.debug(f"No data found for: {email} (total_results={result.total_results if hasattr(result, 'total_results') else 'N/A'})")
                return
            
            result_line = create_output_line(result, email)
            
            has_data = False
            if OUTPUT_ALL:
                has_data = True
            else:
                if hasattr(result, 'phone_numbers') and result.phone_numbers:
                    has_data = True
                if hasattr(result, 'addresses') and result.addresses:
                    has_data = True
                if hasattr(result, 'person') and result.person and result.person.name:
                    has_data = True
                if hasattr(result, 'emails') and result.emails:
                    has_data = True
                
                if TLO_ENRICHMENT:
                    if hasattr(result, 'phone_numbers_full') and result.phone_numbers_full:
                        has_data = True
                    if hasattr(result, 'addresses_structured') and result.addresses_structured:
                        has_data = True
                    if hasattr(result, 'all_names') and result.all_names:
                        has_data = True
                    if hasattr(result, 'alternative_names') and result.alternative_names:
                        has_data = True
                    if hasattr(result, 'all_dobs') and result.all_dobs:
                        has_data = True
                    if hasattr(result, 'related_persons') and result.related_persons:
                        has_data = True
                    if hasattr(result, 'criminal_records') and result.criminal_records:
                        has_data = True
                    if hasattr(result, 'censored_numbers') and result.censored_numbers:
                        has_data = True
                    if hasattr(result, 'confirmed_numbers') and result.confirmed_numbers:
                        has_data = True
                    if hasattr(result, 'other_emails') and result.other_emails:
                        has_data = True
            
            if result_line and has_data:
                with open(output_file, 'a', encoding=OUTPUT_ENCODING) as f:
                    write_result_record(f, result, email)
                
                data_fields = []
                if hasattr(result, 'phone_numbers') and result.phone_numbers:
                    data_fields.append(f"{len(result.phone_numbers)} phones")
                if hasattr(result, 'addresses') and result.addresses:
                    data_fields.append(f"{len(result.addresses)} addresses")
                if hasattr(result, 'person') and result.person and result.person.name:
                    data_fields.append("person")
                if TLO_ENRICHMENT:
                    if hasattr(result, 'phone_numbers_full') and result.phone_numbers_full:
                        data_fields.append(f"{len(result.phone_numbers_full)} TLO phones")
                    if hasattr(result, 'addresses_structured') and result.addresses_structured:
                        data_fields.append(f"{len(result.addresses_structured)} TLO addresses")
                    if hasattr(result, 'all_names') and result.all_names:
                        data_fields.append(f"{len(result.all_names)} name records")
                
                actual_total = 0
                if hasattr(result, 'phone_numbers') and result.phone_numbers:
                    actual_total += len(result.phone_numbers)
                if hasattr(result, 'addresses') and result.addresses:
                    actual_total += len(result.addresses)
                if hasattr(result, 'person') and result.person and result.person.name:
                    actual_total += 1
                if hasattr(result, 'emails') and result.emails:
                    actual_total += len(result.emails)
                if TLO_ENRICHMENT:
                    if hasattr(result, 'phone_numbers_full') and result.phone_numbers_full:
                        actual_total += len(result.phone_numbers_full)
                    if hasattr(result, 'addresses_structured') and result.addresses_structured:
                        actual_total += len(result.addresses_structured)
                    if hasattr(result, 'all_names') and result.all_names:
                        actual_total += len(result.all_names)
                    if hasattr(result, 'alternative_names') and result.alternative_names:
                        actual_total += len(result.alternative_names)
                    if hasattr(result, 'all_dobs') and result.all_dobs:
                        actual_total += len(result.all_dobs)
                    if hasattr(result, 'related_persons') and result.related_persons:
                        actual_total += len(result.related_persons)
                    if hasattr(result, 'criminal_records') and result.criminal_records:
                        actual_total += len(result.criminal_records)
                    if hasattr(result, 'censored_numbers') and result.censored_numbers:
                        actual_total += len(result.censored_numbers)
                    if hasattr(result, 'confirmed_numbers') and result.confirmed_numbers:
                        actual_total += len(result.confirmed_numbers)
                    if hasattr(result, 'other_emails') and result.other_emails:
                        actual_total += len(result.other_emails)
                
                search_cost_str = "N/A"
                if hasattr(result, 'pricing') and result.pricing:
                    if hasattr(result.pricing, 'total_cost') and result.pricing.total_cost is not None:
                        search_cost_str = f"${result.pricing.total_cost:.4f}"
                    elif hasattr(result.pricing, 'search_cost') and result.pricing.search_cost is not None:
                        search_cost_str = f"${result.pricing.search_cost:.4f}"
                elif hasattr(result, 'search_cost') and result.search_cost is not None:
                    search_cost_str = f"${result.search_cost:.4f}"
                
                if hasattr(result, 'pricing') and result.pricing and hasattr(result, 'search_cost'):
                    if hasattr(result.pricing, 'total_cost') and result.pricing.total_cost != result.search_cost:
                        logger.debug(f"Pricing mismatch for {email}: pricing.total_cost={result.pricing.total_cost}, result.search_cost={result.search_cost}")
                
                logger.info(f"Found data for: {email} - {', '.join(data_fields)} (total_items={actual_total}, search_cost={search_cost_str})")
            else:
                debug_info = []
                if hasattr(result, 'total_results'):
                    debug_info.append(f"total_results={result.total_results}")
                if hasattr(result, 'phone_numbers'):
                    debug_info.append(f"phone_numbers={len(result.phone_numbers) if result.phone_numbers else 0}")
                if hasattr(result, 'addresses'):
                    debug_info.append(f"addresses={len(result.addresses) if result.addresses else 0}")
                if TLO_ENRICHMENT:
                    if hasattr(result, 'phone_numbers_full'):
                        debug_info.append(f"phone_numbers_full={len(result.phone_numbers_full) if result.phone_numbers_full else 0}")
                    if hasattr(result, 'addresses_structured'):
                        debug_info.append(f"addresses_structured={len(result.addresses_structured) if result.addresses_structured else 0}")
                    if hasattr(result, 'all_names'):
                        debug_info.append(f"all_names={len(result.all_names) if result.all_names else 0}")
                
                logger.debug(f"No significant data for: {email} ({', '.join(debug_info)})")
            
            return

        except SearchAPIError as e:
            error_str = str(e)
            
            if "No data found" in error_str:
                if OUTPUT_ALL:
                    with open(output_file, 'a', encoding=OUTPUT_ENCODING) as f:
                        write_result_record(f, None, email)
                    logger.debug(f"No data found for: {email}")
                return
            
            if "403" in error_str or "Request failed: 403" in error_str:
                logger.warning(f"Rate limited (403) for {email}: {error_str}")
                if attempt == MAX_RETRIES - 1:
                    error_line = f"{email} | ERROR: Rate limited (403) - Too many requests"
                    with open(output_file, 'a', encoding=OUTPUT_ENCODING) as f:
                        write_error_record(f, error_line)
                    return
                else:
                    import time
                    delay = (RETRY_DELAY_BASE ** attempt) * 5
                    logger.warning(f"Waiting {delay} seconds before retry for {email}")
                    time.sleep(delay)
                    continue
            
            if isinstance(e, (AuthenticationError, InsufficientBalanceError, ValidationError)):
                error_line = handle_api_error(e, email)
                with open(output_file, 'a', encoding=OUTPUT_ENCODING) as f:
                    write_error_record(f, error_line)
                return
            
            elif isinstance(e, (RateLimitError, TimeoutError, NetworkError, ServerError)):
                if attempt == MAX_RETRIES - 1:
                    error_line = handle_api_error(e, email)
                    with open(output_file, 'a', encoding=OUTPUT_ENCODING) as f:
                        write_error_record(f, error_line)
                    return
                else:
                    import time
                    delay = RETRY_DELAY_BASE ** attempt
                    logger.warning(f"Retrying {email} in {delay} seconds (attempt {attempt + 1}/{MAX_RETRIES})")
                    time.sleep(delay)
            else:
                logger.error(f"Search API error for {email}: {error_str}")
                if attempt == MAX_RETRIES - 1:
                    error_line = f"{email} | ERROR: Search API error - {error_str}"
                    with open(output_file, 'a', encoding=OUTPUT_ENCODING) as f:
                        write_error_record(f, error_line)
                else:
                    import time
                    delay = RETRY_DELAY_BASE ** attempt
                    time.sleep(delay)
        
        except Exception as e:
            logger.error(f"Unexpected error for {email}: {str(e)}")
            if attempt == MAX_RETRIES - 1:
                error_line = f"{email} | ERROR: Unexpected error - {str(e)}"
                with open(output_file, 'a', encoding=OUTPUT_ENCODING) as f:
                    write_error_record(f, error_line)
            else:
                import time
                delay = RETRY_DELAY_BASE ** attempt
                time.sleep(delay)


def main(emails: List[str], output_file: str) -> None:
    """Main function to process emails with proper error handling."""
    if not api_key:
        logger.error("API key is required. Please set the api_key variable.")
        return
    
    try:
        config = SearchAPIConfig(api_key=api_key, debug_mode=False)
        api_client = SearchAPI(config=config)
        
        api_client.session = optimize_existing_session(api_client.session)
        
        try:
            balance_info = api_client.get_balance()
            logger.info(f"Current balance: ${balance_info.current_balance}")
            
            base_cost = 0.0025
            feature_costs = 0.0
            if HOUSE_VALUE:
                feature_costs += 0.0015
            if EXTRA_INFO:
                feature_costs += 0.0015
            if CARRIER_INFO:
                feature_costs += 0.0005
            if TLO_ENRICHMENT:
                feature_costs += 0.0030
            
            estimated_cost = len(emails) * (base_cost + feature_costs)
            if balance_info.current_balance < estimated_cost:
                logger.warning(f"Insufficient balance for all searches. Current: ${balance_info.current_balance}, Estimated needed: ${estimated_cost}")
        except Exception as e:
            logger.warning(f"Could not check balance: {e}")
        
        logger.info(f"Starting to process {len(emails)} emails with {MAX_WORKERS} workers")
        logger.info(f"Output fields: {', '.join(get_output_field_order())}")
        logger.info(f"Connection pool: max {CONNECTION_POOL_MAXSIZE} connections per host (auto-scaled from {MAX_WORKERS} workers)")
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_email = {
                executor.submit(fetch_email_info, email, output_file, api_client): email 
                for email in emails
            }
            
            completed = 0
            for future in as_completed(future_to_email):
                email = future_to_email[future]
                completed += 1
                
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Task failed for {email}: {e}")
                
                if completed % 25 == 0 or completed == len(emails):
                    logger.info(f"Progress: {completed}/{len(emails)} emails processed")
        
        logger.info("Processing complete!")
        
    except Exception as e:
        logger.error(f"Fatal error in main: {str(e)}")
        traceback.print_exc()
    finally:
        try:
            api_client.close()
        except:
            pass


if __name__ == '__main__':
    # Load persisted config or run interactive setup
    use_configure = '--configure' in sys.argv or '-c' in sys.argv
    config_loaded = load_config()

    if use_configure or not config_loaded:
        interactive_setup()
        if use_configure:
            print("Re-run without --configure to process emails, or continue now.")
            try:
                cont = input("Continue to process emails now? (y/n) [y]: ").strip().lower()
                if cont in ('n', 'no'):
                    sys.exit(0)
            except EOFError:
                pass

    output_file = 'output.txt'

    if OUTPUT_FORMAT == 'json':
        open(output_file, 'w', encoding=OUTPUT_ENCODING).close()
    elif INCLUDE_HEADER:
        header = create_header()
        with open(output_file, 'w', encoding=OUTPUT_ENCODING) as f:
            if header:
                f.write(header + '\n')
    else:
        open(output_file, 'w', encoding=OUTPUT_ENCODING).close()

    try:
        emails = load_emails('emails.txt')
        if not emails:
            logger.error("No valid emails found in emails.txt")
            exit(1)

        logger.info(f"Starting email search with {len(emails)} emails")
        logger.info(f"Configuration: HOUSE_VALUE={HOUSE_VALUE}, EXTRA_INFO={EXTRA_INFO}, CARRIER_INFO={CARRIER_INFO}, TLO_ENRICHMENT={TLO_ENRICHMENT}, RECOVERY_CHECK={RECOVERY_CHECK}")
        logger.info(f"Output fields: {', '.join(get_output_field_order())}")
        if RECOVERY_MODULES:
            logger.info(f"Recovery modules: order={RECOVERY_MODULES.get('module_order')}, enabled={RECOVERY_MODULES.get('enabled_modules')}")

        main(emails, output_file)

        logger.info(f"Processing complete. Results saved to {output_file}")

    except FileNotFoundError:
        logger.error("Error: emails.txt file not found. Please create a file with one email per line.")
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        traceback.print_exc()

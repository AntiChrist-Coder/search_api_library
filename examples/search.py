import json
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LIBRARY_ROOT = os.path.dirname(SCRIPT_DIR)
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'search_api_config.json')

_SEARCH_API_PACKAGE = 'AD-SearchAPI'


def _pip_install(*specs: str) -> None:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', *specs])


def _import_search_api() -> bool:
    try:
        import search_api  # noqa: F401
        return True
    except ImportError:
        return False


def _import_tkinter() -> bool:
    try:
        import tkinter  # noqa: F401
        return True
    except ImportError:
        return False


def _ensure_tkinter(required: bool = False) -> None:
    """Verify tkinter is available (needed for --gui). Cannot be installed via pip on most platforms."""
    if _import_tkinter():
        return
    if not required:
        return

    py_ver = f'{sys.version_info.major}.{sys.version_info.minor}'
    print('\ntkinter is required for the GUI (--gui) but is not available in this Python install.\n')
    if sys.platform == 'win32':
        print('Windows: Re-run the Python installer → Modify → enable "tcl/tk and IDLE".')
    elif sys.platform == 'darwin':
        print('macOS:  brew install python-tk')
        print('        Or reinstall Python from python.org with default options.')
    else:
        print(f'Linux (Debian/Ubuntu):  sudo apt install python{py_ver}-tk')
        print('Linux (Fedora/RHEL):    sudo dnf install python3-tkinter')
    print('\nOr use the terminal setup instead:  python search.py --configure-cli\n')
    sys.exit(1)


def _ensure_dependencies() -> None:
    """Install AD-SearchAPI and verify tkinter when the GUI is requested."""
    if os.environ.get('SEARCH_API_SKIP_AUTO_INSTALL'):
        if '--gui' in sys.argv:
            _ensure_tkinter(required=True)
        return
    if os.environ.get('_SEARCH_API_AUTO_INSTALL_DONE'):
        if '--gui' in sys.argv:
            _ensure_tkinter(required=True)
        return

    if _import_search_api():
        if '--gui' in sys.argv:
            _ensure_tkinter(required=True)
        return

    os.environ['_SEARCH_API_AUTO_INSTALL_DONE'] = '1'
    print(f'Missing dependencies — installing {_SEARCH_API_PACKAGE}…')

    setup_py = os.path.join(LIBRARY_ROOT, 'setup.py')
    installed = False

    try:
        _pip_install(_SEARCH_API_PACKAGE)
        installed = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        if os.path.isfile(setup_py):
            print('PyPI install failed; trying local library (editable install)…')
            try:
                _pip_install('-e', LIBRARY_ROOT)
                installed = True
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass

    if not installed:
        print('\nAutomatic install failed. Install manually:')
        print(f'  pip install {_SEARCH_API_PACKAGE}')
        if os.path.isfile(setup_py):
            print(f'  pip install -e "{LIBRARY_ROOT}"')
        sys.exit(1)

    if not _import_search_api():
        print('\nInstall finished but search_api still could not be imported.')
        print(f'  pip install {_SEARCH_API_PACKAGE}')
        sys.exit(1)

    print('Dependencies installed.\n')

    if '--gui' in sys.argv:
        _ensure_tkinter(required=True)


if '--no-auto-install' in sys.argv:
    os.environ['SEARCH_API_SKIP_AUTO_INSTALL'] = '1'
    sys.argv = [arg for arg in sys.argv if arg != '--no-auto-install']

_ensure_dependencies()

import traceback
import webbrowser
import threading
import math
import queue
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, Callable, Set
from search_api import SearchAPI, SearchAPIConfig
from search_api.exceptions import (
    SearchAPIError, AuthenticationError, ValidationError, RateLimitError,
    InsufficientBalanceError, ServerError, NetworkError, TimeoutError
)

# Config file path (same directory as this script) - persisted across runs

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
# Config is a simple list of field names, e.g. ["email", "name", "phone_numbers", "recovery_phone"]
# Duplicate API fields (phone_numbers_full, censored_numbers, etc.) merge automatically into the
# simple names below — everything is still supported, users just pick clean column names.
OUTPUT_FIELD_LABELS: Dict[str, str] = {
    'email': 'Email',
    'name': 'Name',
    'dob': 'DOB',
    'age': 'Age',
    'gender': 'Gender',
    'phone_numbers': 'Phone Numbers',
    'addresses': 'Addresses',
    'emails': 'Emails',
    'recovery_phone': 'Recovery Phone',
    'companies': 'Companies',
    'industry': 'Industry',
    'linkedin': 'LinkedIn',
    'education': 'Education',
    'location_metro': 'Metro Area',
    'social_media': 'Social Media',
    'alternative_names': 'Alt Names',
    'all_names': 'All Names',
    'all_dobs': 'All DOBs',
    'related_persons': 'Related People',
    'criminal_records': 'Criminal Records',
    'total_results': 'Result Count',
    'search_cost': 'Cost',
    'pricing': 'Pricing Breakdown',
    'email_valid': 'Email Valid',
    'email_type': 'Email Type',
}

OUTPUT_FIELD_GROUPS: List[Tuple[str, List[str]]] = [
    ('Core', ['email', 'name', 'dob', 'age', 'gender']),
    ('Contact', ['phone_numbers', 'addresses', 'emails']),
    ('Recovery', ['recovery_phone']),
    ('Profile', ['companies', 'industry', 'linkedin', 'education', 'location_metro', 'social_media']),
    ('TLO', ['alternative_names', 'all_names', 'all_dobs', 'related_persons', 'criminal_records']),
    ('Meta', ['total_results', 'search_cost', 'pricing', 'email_valid', 'email_type']),
]

OUTPUT_FIELD_CATALOG: List[Tuple[str, str]] = [
    (key, OUTPUT_FIELD_LABELS[key]) for _, keys in OUTPUT_FIELD_GROUPS for key in keys
]

OUTPUT_FIELD_PRESETS: Dict[str, List[str]] = {
    'default': ['email', 'name', 'dob', 'age', 'phone_numbers'],
    'phones': ['email', 'phone_numbers', 'recovery_phone'],
    'contact': ['email', 'name', 'phone_numbers', 'addresses', 'emails'],
    'full': [key for key, _ in OUTPUT_FIELD_CATALOG],
}

OUTPUT_FIELDS_DEFAULT = list(OUTPUT_FIELD_PRESETS['default'])
OUTPUT_FIELDS: List[str] = list(OUTPUT_FIELDS_DEFAULT)

# Search mode: 'email' or 'phone'
SEARCH_MODE = 'email'

EMAIL_ONLY_FIELDS = frozenset({'email', 'recovery_phone', 'email_valid', 'email_type'})

OUTPUT_FIELD_LABELS['phone'] = 'Phone'

OUTPUT_FIELD_PRESETS_PHONE: Dict[str, List[str]] = {
    'default': ['phone', 'name', 'dob', 'age', 'phone_numbers'],
    'phones': ['phone', 'phone_numbers'],
    'contact': ['phone', 'name', 'phone_numbers', 'addresses', 'emails'],
    'full': [
        'phone', 'name', 'dob', 'age', 'gender', 'phone_numbers', 'addresses', 'emails',
        'companies', 'industry', 'linkedin', 'education', 'location_metro', 'social_media',
        'alternative_names', 'all_names', 'all_dobs', 'related_persons', 'criminal_records',
        'total_results', 'search_cost', 'pricing',
    ],
}

OUTPUT_FIELDS_BY_MODE: Dict[str, List[str]] = {
    'email': list(OUTPUT_FIELDS_DEFAULT),
    'phone': list(OUTPUT_FIELD_PRESETS_PHONE['default']),
}
OUTPUT_REQUIREMENTS_BY_MODE: Dict[str, List[str]] = {'email': [], 'phone': []}

SIMPLE_OUTPUT_FIELDS_EMAIL: List[Tuple[str, str]] = [
    ('email', 'Email'), ('name', 'Name'), ('dob', 'Date of birth'), ('age', 'Age'),
    ('phone_numbers', 'Phone numbers'), ('recovery_phone', 'Recovery phone'),
    ('addresses', 'Addresses'), ('emails', 'Emails'),
]
SIMPLE_OUTPUT_FIELDS_PHONE: List[Tuple[str, str]] = [
    ('phone', 'Phone'), ('name', 'Name'), ('dob', 'Date of birth'), ('age', 'Age'),
    ('phone_numbers', 'Phone numbers'), ('addresses', 'Addresses'), ('emails', 'Emails'),
]
REQUIREMENT_FIELDS_EMAIL: List[Tuple[str, str]] = [
    ('phone_numbers', 'Phone numbers'), ('recovery_phone', 'Recovery phone'),
    ('name', 'Name'), ('addresses', 'Addresses'), ('emails', 'Emails'),
]
REQUIREMENT_FIELDS_PHONE: List[Tuple[str, str]] = [
    ('phone_numbers', 'Phone numbers'), ('name', 'Name'),
    ('addresses', 'Addresses'), ('emails', 'Emails'),
]

# Only write a line when the result has ALL of these fields, e.g. ["phone_numbers", "name"]
OUTPUT_REQUIREMENTS: List[str] = []

# Optional callbacks for GUI live output during batch runs
LIVE_OUTPUT_CALLBACK: Optional[Callable[[str], None]] = None
ON_PROGRESS_CALLBACK: Optional[Callable[[int, int, str], None]] = None


def is_email_mode(mode: str = None) -> bool:
    return (mode or SEARCH_MODE) == 'email'


def get_mode_field_labels(mode: str = None) -> Dict[str, str]:
    mode = mode or SEARCH_MODE
    if is_email_mode(mode):
        return dict(OUTPUT_FIELD_LABELS)
    labels = {k: v for k, v in OUTPUT_FIELD_LABELS.items() if k not in EMAIL_ONLY_FIELDS}
    labels['phone'] = 'Phone'
    return labels


def get_mode_presets(mode: str = None) -> Dict[str, List[str]]:
    return OUTPUT_FIELD_PRESETS if is_email_mode(mode) else OUTPUT_FIELD_PRESETS_PHONE


def get_mode_simple_fields(mode: str = None) -> List[Tuple[str, str]]:
    return SIMPLE_OUTPUT_FIELDS_EMAIL if is_email_mode(mode) else SIMPLE_OUTPUT_FIELDS_PHONE


def get_mode_requirement_fields(mode: str = None) -> List[Tuple[str, str]]:
    return REQUIREMENT_FIELDS_EMAIL if is_email_mode(mode) else REQUIREMENT_FIELDS_PHONE


def get_input_filename(mode: str = None) -> str:
    return 'emails.txt' if is_email_mode(mode) else 'phones.txt'


def get_output_filename(mode: str = None) -> str:
    return 'output.txt' if is_email_mode(mode) else 'output_phone.txt'


def persist_current_mode_settings() -> None:
    OUTPUT_FIELDS_BY_MODE[SEARCH_MODE] = list(OUTPUT_FIELDS)
    OUTPUT_REQUIREMENTS_BY_MODE[SEARCH_MODE] = list(OUTPUT_REQUIREMENTS)


def apply_mode_settings(mode: str) -> None:
    global OUTPUT_FIELDS, OUTPUT_REQUIREMENTS, SEARCH_MODE
    if mode != SEARCH_MODE:
        persist_current_mode_settings()
    SEARCH_MODE = mode
    OUTPUT_FIELDS.clear()
    OUTPUT_FIELDS.extend(OUTPUT_FIELDS_BY_MODE.get(mode, get_mode_presets(mode)['default']))
    OUTPUT_REQUIREMENTS.clear()
    OUTPUT_REQUIREMENTS.extend(OUTPUT_REQUIREMENTS_BY_MODE.get(mode, []))


def set_search_mode(mode: str) -> None:
    if mode not in ('email', 'phone'):
        mode = 'email'
    if mode != SEARCH_MODE:
        apply_mode_settings(mode)


LEGACY_FIELD_ALIASES = {
    'recovery_check': 'recovery_phone',
    'censored_numbers': 'phone_numbers',
    'phone_numbers_full': 'phone_numbers',
    'confirmed_numbers': 'phone_numbers',
    'addresses_structured': 'addresses',
    'other_emails': 'emails',
    'linkedin_url': 'linkedin',
    'linkedin_id': 'linkedin',
    'social_media_identifiers': 'social_media',
    'pricing_breakdown': 'pricing',
    'location': 'location_metro',
}

LEGACY_FIELD_NUMBERS = {
    1: 'email', 2: 'name', 3: 'dob', 4: 'age', 5: 'gender', 6: 'phone_numbers',
    7: 'addresses', 8: 'addresses', 9: 'emails', 10: 'emails', 11: 'email_valid',
    12: 'email_type', 13: 'total_results', 14: 'search_cost', 15: 'pricing',
    16: 'location_metro', 17: 'companies', 18: 'industry', 19: 'linkedin', 20: 'linkedin',
    21: 'social_media', 22: 'education', 23: 'recovery_phone', 24: 'phone_numbers',
    25: 'alternative_names', 26: 'all_names', 27: 'all_dobs', 28: 'related_persons',
    29: 'criminal_records', 30: 'phone_numbers', 31: 'phone_numbers',
}

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

def _normalize_field_name(name: str, mode: str = None) -> Optional[str]:
    key = LEGACY_FIELD_ALIASES.get(name.strip().lower(), name.strip().lower())
    labels = get_mode_field_labels(mode)
    if key in labels:
        return key
    return None


def _resolve_output_field_preset(name: str, mode: str = None) -> Optional[List[str]]:
    preset = get_mode_presets(mode).get(name.strip().lower())
    if preset is not None:
        return list(preset)
    return None


def print_output_field_guide() -> None:
    """Print grouped field names for interactive setup."""
    for group_name, keys in OUTPUT_FIELD_GROUPS:
        labels = ', '.join(f"{k} ({OUTPUT_FIELD_LABELS[k]})" for k in keys)
        print(f"  {group_name}: {labels}")
    print("  Presets: default | phones | contact | full")


def _normalize_output_fields(raw_items: List[Any]) -> List[str]:
    """Convert config values to a deduplicated ordered list of field names."""
    result: List[str] = []
    seen = set()
    for item in raw_items:
        if isinstance(item, str):
            preset = _resolve_output_field_preset(item)
            if preset:
                for key in preset:
                    if key not in seen:
                        seen.add(key)
                        result.append(key)
                continue
        if isinstance(item, int):
            key = LEGACY_FIELD_NUMBERS.get(item)
        else:
            key = _normalize_field_name(str(item))
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result or list(get_mode_presets()['default'])


def load_output_fields_from_config(
    raw,
    output_fields: List[str] = None,
) -> None:
    """Load output_fields from config: list of names, legacy numbers, or legacy bool dict."""
    target = output_fields if output_fields is not None else OUTPUT_FIELDS
    target.clear()

    if isinstance(raw, list):
        target.extend(_normalize_output_fields(raw))
    elif isinstance(raw, dict):
        enabled = []
        for key, on in raw.items():
            if not on:
                continue
            normalized = _normalize_field_name(key)
            if normalized:
                enabled.append(normalized)
        target.extend(_normalize_output_fields(enabled))
    elif isinstance(raw, str) and raw.strip():
        preset = _resolve_output_field_preset(raw.strip())
        if preset:
            target.extend(preset)
        else:
            parts = [p.strip() for p in raw.replace(';', ',').split(',') if p.strip()]
            target.extend(_normalize_output_fields(parts))
    else:
        target.extend(get_mode_presets()['default'])


def get_enabled_output_fields() -> List[str]:
    """Return configured output fields in order."""
    return list(OUTPUT_FIELDS)


def apply_output_field_selection(selected_keys: List[str]) -> None:
    """Replace OUTPUT_FIELDS with a validated ordered list."""
    global OUTPUT_FIELDS
    OUTPUT_FIELDS.clear()
    OUTPUT_FIELDS.extend(_normalize_output_fields(selected_keys))


def ensure_recovery_phone_output_field() -> None:
    """When recovery verification is on (email mode), include recovery_phone in output columns."""
    global OUTPUT_FIELDS
    if not is_email_mode() or not RECOVERY_CHECK:
        return
    if 'recovery_phone' in OUTPUT_FIELDS:
        return
    # Insert after phone_numbers when present, otherwise after email
    fields = list(OUTPUT_FIELDS)
    if 'phone_numbers' in fields:
        fields.insert(fields.index('phone_numbers') + 1, 'recovery_phone')
    elif 'email' in fields:
        fields.insert(fields.index('email') + 1, 'recovery_phone')
    else:
        fields.append('recovery_phone')
    OUTPUT_FIELDS.clear()
    OUTPUT_FIELDS.extend(fields)


def count_phones_in_result(
    result,
    tlo_enrichment: bool = None,
    recovery_check: bool = None,
) -> int:
    """Count phone numbers on a search result (includes recovery match when present)."""
    tlo_enrichment = TLO_ENRICHMENT if tlo_enrichment is None else tlo_enrichment
    recovery_check = RECOVERY_CHECK if recovery_check is None else recovery_check
    count = len(collect_all_phone_numbers(result, tlo_enrichment=tlo_enrichment))
    if recovery_check and hasattr(result, 'recovery_check') and result.recovery_check:
        rc = result.recovery_check
        if getattr(rc, 'matched', False) or getattr(rc, 'matched_number', None):
            count = max(count, 1)
    return count


def collect_all_emails_from_result(result, tlo_enrichment: bool = None) -> List[str]:
    """Collect unique emails from all available result sources."""
    tlo_enrichment = TLO_ENRICHMENT if tlo_enrichment is None else tlo_enrichment
    emails: List[str] = []
    seen = set()
    if hasattr(result, 'emails') and result.emails:
        for email in result.emails:
            if email and email not in seen:
                seen.add(email)
                emails.append(email)
    if tlo_enrichment and hasattr(result, 'other_emails') and result.other_emails:
        for email in result.other_emails:
            if email and email not in seen:
                seen.add(email)
                emails.append(email)
    return emails


def collect_all_addresses_from_result(result, tlo_enrichment: bool = None) -> int:
    """Count addresses from regular and structured TLO sources."""
    tlo_enrichment = TLO_ENRICHMENT if tlo_enrichment is None else tlo_enrichment
    count = len(result.addresses) if hasattr(result, 'addresses') and result.addresses else 0
    if tlo_enrichment and hasattr(result, 'addresses_structured') and result.addresses_structured:
        count = max(count, len(result.addresses_structured))
    return count


def count_field_in_result(
    result,
    field: str,
    tlo_enrichment: bool = None,
    recovery_check: bool = None,
) -> int:
    """Return how many of `field` exist on a result (presence fields return 0 or 1)."""
    tlo_enrichment = TLO_ENRICHMENT if tlo_enrichment is None else tlo_enrichment
    recovery_check = RECOVERY_CHECK if recovery_check is None else recovery_check
    field = LEGACY_FIELD_ALIASES.get(field, field)

    if field == 'phone_numbers':
        return len(collect_all_phone_numbers(result, tlo_enrichment=tlo_enrichment))
    if field == 'recovery_phone':
        if recovery_check and hasattr(result, 'recovery_check') and result.recovery_check:
            if getattr(result.recovery_check, 'matched_number', None):
                return 1
        return 0
    if field == 'addresses':
        return collect_all_addresses_from_result(result, tlo_enrichment=tlo_enrichment)
    if field == 'emails':
        return len(collect_all_emails_from_result(result, tlo_enrichment=tlo_enrichment))
    if field == 'name':
        return 1 if hasattr(result, 'person') and result.person and result.person.name else 0
    if field == 'dob':
        return 1 if hasattr(result, 'person') and result.person and getattr(result.person, 'dob', None) else 0
    if field == 'age':
        return 1 if hasattr(result, 'person') and result.person and getattr(result.person, 'age', None) else 0
    if field == 'gender':
        return 1 if hasattr(result, 'person') and result.person and getattr(result.person, 'gender', None) else 0
    if field == 'email':
        return 1 if getattr(result, 'email', None) else 0
    if field == 'phone':
        return 1
    if field == 'alternative_names':
        return len(result.alternative_names) if hasattr(result, 'alternative_names') and result.alternative_names else 0
    if field == 'all_names':
        return len(result.all_names) if hasattr(result, 'all_names') and result.all_names else 0
    if field == 'all_dobs':
        return len(result.all_dobs) if hasattr(result, 'all_dobs') and result.all_dobs else 0
    if field == 'related_persons':
        return len(result.related_persons) if hasattr(result, 'related_persons') and result.related_persons else 0
    if field == 'criminal_records':
        return len(result.criminal_records) if hasattr(result, 'criminal_records') and result.criminal_records else 0
    if field == 'companies':
        return len(result.companies) if hasattr(result, 'companies') and result.companies else 0
    if field == 'education':
        return len(result.education) if hasattr(result, 'education') and result.education else 0
    if field == 'social_media':
        return len(result.social_media_identifiers) if hasattr(result, 'social_media_identifiers') and result.social_media_identifiers else 0
    if field == 'linkedin':
        has_url = hasattr(result, 'linkedin_url') and result.linkedin_url
        has_id = hasattr(result, 'linkedin_id') and result.linkedin_id
        return 1 if has_url or has_id else 0
    if field == 'industry':
        return 1 if hasattr(result, 'industry') and result.industry else 0
    if field == 'location_metro':
        return 1 if hasattr(result, 'location_metro') and result.location_metro else 0
    if field == 'email_valid':
        return 1 if getattr(result, 'email_valid', False) else 0
    if field == 'email_type':
        return 1 if getattr(result, 'email_type', None) else 0
    return 0


def has_field_in_result(
    result,
    field: str,
    tlo_enrichment: bool = None,
    recovery_check: bool = None,
) -> bool:
    """Return True when the result has any value for this field."""
    return count_field_in_result(result, field, tlo_enrichment, recovery_check) > 0


def _normalize_requirement_field(name: str) -> Optional[str]:
    field = _normalize_field_name(name)
    if field:
        return field
    if name.strip().lower() == 'phone':
        return 'phone'
    return None


def _normalize_requirement_fields(raw_items: List[Any]) -> List[str]:
    """Convert config values to a deduplicated list of required field names."""
    result: List[str] = []
    seen = set()
    for item in raw_items:
        text = str(item).strip()
        if not text:
            continue
        if ':' in text:
            text = text.split(':', 1)[0].strip()
        field = _normalize_requirement_field(text)
        if field and field not in seen:
            seen.add(field)
            result.append(field)
    return result


def format_output_requirements(requirements: List[str] = None) -> str:
    requirements = requirements if requirements is not None else OUTPUT_REQUIREMENTS
    if not requirements:
        return '(none)'
    return ', '.join(requirements)


def parse_output_requirements(spec: str) -> List[str]:
    """Parse 'phone_numbers,name,recovery_phone'. Legacy 'phone_numbers:1' also works."""
    parts = [p.strip() for p in spec.replace(';', ',').split(',') if p.strip()]
    if spec.strip().lower() == 'phones':
        return ['phone_numbers']
    return _normalize_requirement_fields(parts)


def load_output_requirements_from_config(data: dict) -> None:
    """Load output requirements (list of field names; legacy dict/count formats supported)."""
    global OUTPUT_REQUIREMENTS
    OUTPUT_REQUIREMENTS.clear()
    raw = data.get('output_requirements')
    if isinstance(raw, list):
        OUTPUT_REQUIREMENTS.extend(_normalize_requirement_fields(raw))
    elif isinstance(raw, dict):
        enabled = []
        for key, value in raw.items():
            if value:
                enabled.append(str(key))
        OUTPUT_REQUIREMENTS.extend(_normalize_requirement_fields(enabled))
    elif isinstance(raw, str) and raw.strip():
        OUTPUT_REQUIREMENTS.extend(parse_output_requirements(raw))
    elif 'min_phone_numbers' in data:
        if max(0, int(data.get('min_phone_numbers', 0))) > 0:
            OUTPUT_REQUIREMENTS.append('phone_numbers')


def describe_output_requirements_failure(result) -> str:
    """Explain which required fields were missing."""
    missing = []
    for field in OUTPUT_REQUIREMENTS:
        if not has_field_in_result(result, field):
            label = OUTPUT_FIELD_LABELS.get(field, field)
            missing.append(label)
    return ', '.join(f"missing {m}" for m in missing) if missing else 'unknown'


def prompt_output_requirements(include_recovery: bool = None) -> None:
    """Interactive prompt: pick which fields a result must have."""
    global OUTPUT_REQUIREMENTS
    include_recovery = RECOVERY_CHECK if include_recovery is None else include_recovery

    print("\n--- Output requirements ---")
    print(f"  Current: {format_output_requirements()}")
    print("  A line is only written when the result has ALL selected fields.")
    if OUTPUT_REQUIREMENTS:
        if not _yes_no("  Change output requirements?", default=False):
            return
    elif not _yes_no("  Set output requirements?", default=False):
        return

    candidate_fields = [
        ('phone_numbers', 'Has phone numbers'),
        ('name', 'Has name'),
        ('addresses', 'Has addresses'),
        ('emails', 'Has emails'),
    ]
    if include_recovery:
        candidate_fields.insert(1, ('recovery_phone', 'Has recovery phone'))

    print("\n  Must have (y/n):")
    new_requirements: List[str] = []
    for field, label in candidate_fields:
        if _yes_no(f"  {label} ({field})", field in OUTPUT_REQUIREMENTS):
            new_requirements.append(field)

    print("\n  Other fields (comma-separated), or Enter to skip:")
    print(f"  Available: {', '.join(OUTPUT_FIELD_LABELS.keys())}")
    extra = input("  Also require: ").strip()
    if extra:
        for field in parse_output_requirements(extra):
            if field not in new_requirements:
                new_requirements.append(field)

    OUTPUT_REQUIREMENTS.clear()
    OUTPUT_REQUIREMENTS.extend(new_requirements)
    print(f"  Using requirements: {format_output_requirements()}")


def print_output_requirement_guide() -> None:
    print(f"  Current: {format_output_requirements()}")
    print("  Format: comma-separated field names, e.g. phone_numbers,name,recovery_phone")


def apply_output_requirements_spec(spec: str) -> None:
    global OUTPUT_REQUIREMENTS
    if spec.strip().lower() in ('none', 'clear', ''):
        OUTPUT_REQUIREMENTS.clear()
        return
    OUTPUT_REQUIREMENTS.clear()
    OUTPUT_REQUIREMENTS.extend(parse_output_requirements(spec))


def meets_output_requirements(
    result,
    requirements: List[str] = None,
    tlo_enrichment: bool = None,
    recovery_check: bool = None,
) -> bool:
    """Return False when the result is missing a required field."""
    requirements = requirements if requirements is not None else OUTPUT_REQUIREMENTS
    if not requirements:
        return True
    for field in requirements:
        if not has_field_in_result(result, field, tlo_enrichment, recovery_check):
            return False
    return True


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
    global TLO_ENRICHMENT, RECOVERY_CHECK, RECOVERY_MODULES, OUTPUT_FIELDS, OUTPUT_REQUIREMENTS
    global OUTPUT_FORMAT, OUTPUT_SEPARATOR, OUTPUT_CSV_DELIMITER, SEARCH_MODE
    if not os.path.isfile(CONFIG_PATH):
        return False
    try:
        with open(CONFIG_PATH, 'r', encoding='UTF-8') as f:
            data = json.load(f)
        api_key = data.get('api_key', api_key)
        SEARCH_MODE = data.get('search_mode', SEARCH_MODE)
        if SEARCH_MODE not in ('email', 'phone'):
            SEARCH_MODE = 'email'
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

        if 'output_fields_by_mode' in data:
            for mode_key in ('email', 'phone'):
                if mode_key in data['output_fields_by_mode']:
                    OUTPUT_FIELDS_BY_MODE[mode_key] = _normalize_output_fields(data['output_fields_by_mode'][mode_key])
        elif 'output_fields' in data:
            OUTPUT_FIELDS_BY_MODE[SEARCH_MODE] = _normalize_output_fields(data['output_fields'])

        if 'output_requirements_by_mode' in data:
            for mode_key in ('email', 'phone'):
                if mode_key in data['output_requirements_by_mode']:
                    OUTPUT_REQUIREMENTS_BY_MODE[mode_key] = _normalize_requirement_fields(
                        data['output_requirements_by_mode'][mode_key]
                    )
        else:
            load_output_requirements_from_config(data)

        apply_mode_settings(SEARCH_MODE)
        return True
    except Exception as e:
        logging.warning(f"Could not load config from {CONFIG_PATH}: {e}")
        return False


def save_config() -> None:
    """Save current options and output fields to CONFIG_PATH."""
    persist_current_mode_settings()
    data = {
        'search_mode': SEARCH_MODE,
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
        'output_fields_by_mode': {
            'email': OUTPUT_FIELDS_BY_MODE.get('email', get_mode_presets('email')['default']),
            'phone': OUTPUT_FIELDS_BY_MODE.get('phone', get_mode_presets('phone')['default']),
        },
        'output_requirements_by_mode': {
            'email': OUTPUT_REQUIREMENTS_BY_MODE.get('email', []),
            'phone': OUTPUT_REQUIREMENTS_BY_MODE.get('phone', []),
        },
        'output_fields': get_enabled_output_fields(),
        'output_requirements': list(OUTPUT_REQUIREMENTS),
    }
    with open(CONFIG_PATH, 'w', encoding='UTF-8') as f:
        json.dump(data, f, indent=2)
    print(f"  Configuration saved to {CONFIG_PATH}")


def simple_cli_setup() -> None:
    """Minimal terminal setup — presets only, no field lists."""
    global api_key, HOUSE_VALUE, EXTRA_INFO, CARRIER_INFO, TLO_ENRICHMENT, RECOVERY_CHECK
    global RECOVERY_MODULES, OUTPUT_FIELDS, OUTPUT_FORMAT, OUTPUT_ALL, OUTPUT_REQUIREMENTS, SEARCH_MODE

    print("\n=== Search API — Quick setup ===\n")
    print("(For a visual editor run:  python search.py --gui)\n")

    mode_choice = input("Process emails or phones? [email/phone, default email]: ").strip().lower()
    set_search_mode('phone' if mode_choice.startswith('p') else 'email')
    input_label = 'email' if is_email_mode() else 'phone'

    if not api_key:
        api_key = input("API key: ").strip()
        if not api_key:
            print("API key required.")
            sys.exit(1)

    print("\nSearch options (y/n):")
    HOUSE_VALUE = _yes_no("  House value", HOUSE_VALUE)
    EXTRA_INFO = _yes_no("  Extra info", EXTRA_INFO)
    CARRIER_INFO = _yes_no("  Carrier info", CARRIER_INFO)
    TLO_ENRICHMENT = _yes_no("  TLO enrichment", TLO_ENRICHMENT)
    if is_email_mode():
        RECOVERY_CHECK = _yes_no("  Recovery phone check", RECOVERY_CHECK)
    else:
        RECOVERY_CHECK = False
    OUTPUT_ALL = _yes_no("  Include not-found lines", OUTPUT_ALL)

    print("\nOutput preset:")
    if is_email_mode():
        print("  1. Basic      — email, name, DOB, age, phones")
        print("  2. Phones      — email, phones, recovery")
        print("  3. Contact     — email, name, phones, addresses, emails")
    else:
        print("  1. Basic      — phone, name, DOB, age, phones")
        print("  2. Phones      — phone, phone numbers")
        print("  3. Contact     — phone, name, phones, addresses, emails")
    print("  4. Everything")
    preset_choice = input("Pick 1–4 [1]: ").strip() or '1'
    preset_map = {'1': 'default', '2': 'phones', '3': 'contact', '4': 'full'}
    apply_output_field_selection(get_mode_presets()[preset_map.get(preset_choice, 'default')])
    if RECOVERY_CHECK:
        ensure_recovery_phone_output_field()

    print("\nOnly output if result has (y/n):")
    OUTPUT_REQUIREMENTS.clear()
    if _yes_no("  Phone numbers", False):
        OUTPUT_REQUIREMENTS.append('phone_numbers')
    if is_email_mode() and RECOVERY_CHECK and _yes_no("  Recovery phone", False):
        OUTPUT_REQUIREMENTS.append('recovery_phone')
    if _yes_no("  Name", False):
        OUTPUT_REQUIREMENTS.append('name')

    OUTPUT_FORMAT = 'text'
    save_config()
    print(f"\nSaved to {CONFIG_PATH} (mode: {SEARCH_MODE}, input: {get_input_filename()})\n")


def interactive_setup() -> None:
    """Legacy name — use GUI if possible, else minimal CLI."""
    try:
        if tk is None:
            raise ImportError('tkinter not available')
        run_config_gui()
    except Exception:
        simple_cli_setup()


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
    return get_enabled_output_fields()


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

    field_labels = get_mode_field_labels()
    enabled_fields = get_output_field_order()
    header_fields = [field_labels.get(field, field) for field in enabled_fields]
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


def _normalize_phone_to_e164(line: str) -> Optional[str]:
    """
    Normalize a phone line to E.164 (+ and digits, 10–15 digits after +).
    Accepts: +44..., 0044..., 44..., (44) 20..., 10-digit US, 11-digit 1+10 US.
    """
    import re
    raw = line.strip()
    if not raw:
        return None
    # Remove common separators (match client's _PHONE_CLEAN_TABLE behavior)
    cleaned = raw.translate(str.maketrans('', '', ' -().'))
    if not cleaned:
        return None
    digits_only = re.compile(r'\d+')
    digits = ''.join(digits_only.findall(cleaned))
    if not digits:
        return None
    if cleaned.startswith('+'):
        e164 = '+' + digits
    elif cleaned.startswith('00') and len(digits) > 2:
        # International prefix 00: drop leading 00 from digits (e.g. 0044... -> +44...)
        e164 = '+' + digits.lstrip('0') if digits.lstrip('0') else None
        if not e164 or e164 == '+':
            return None
    elif len(digits) == 10:
        e164 = '+1' + digits
    elif len(digits) == 11 and digits.startswith('1'):
        e164 = '+' + digits
    elif 9 <= len(digits) <= 15:
        e164 = '+' + digits
    else:
        return None
    # E.164: + followed by 10–15 digits
    num_part = e164[1:]
    if not num_part.isdigit() or len(num_part) < 10 or len(num_part) > 15:
        return None
    return e164


def load_phones(file_path: str) -> List[str]:
    """Load phone numbers from file. Normalizes to E.164 (international: +country + number)."""
    try:
        with open(file_path, 'r', encoding="UTF-8") as f:
            raw = [line.strip() for line in f if line.strip()]
        valid_phones = []
        for line in raw:
            e164 = _normalize_phone_to_e164(line)
            if e164:
                valid_phones.append(e164)
            else:
                logger.warning(f"Invalid phone format: {line.strip()}")
        logger.info(f"Loaded {len(valid_phones)} valid phone numbers from {file_path}")
        return valid_phones
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
        raise
    except Exception as e:
        logger.error(f"Error loading phones from {file_path}: {str(e)}")
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


def _extract_phone_number(value) -> Optional[str]:
    if not value:
        return None
    if hasattr(value, 'number') and value.number:
        return str(value.number).strip()
    text = str(value).strip()
    return text or None


def collect_all_phone_numbers(result, tlo_enrichment: bool = None) -> List[str]:
    """Collect unique phone numbers from all available result sources."""
    tlo_enrichment = TLO_ENRICHMENT if tlo_enrichment is None else tlo_enrichment
    numbers: List[str] = []
    seen = set()

    def add(value) -> None:
        num = _extract_phone_number(value)
        if num and num not in seen:
            seen.add(num)
            numbers.append(num)

    if hasattr(result, 'phone_numbers') and result.phone_numbers:
        for phone in result.phone_numbers:
            add(phone)
    if tlo_enrichment:
        if hasattr(result, 'phone_numbers_full') and result.phone_numbers_full:
            for phone in result.phone_numbers_full:
                add(phone)
        if hasattr(result, 'confirmed_numbers') and result.confirmed_numbers:
            for phone in result.confirmed_numbers:
                add(phone)
        if hasattr(result, 'censored_numbers') and result.censored_numbers:
            for phone in result.censored_numbers:
                add(phone)
    return numbers


def format_all_phones_from_result(result) -> str:
    """Format all phone numbers as a simple semicolon-separated list."""
    numbers = collect_all_phone_numbers(result)
    if not numbers:
        return 'None' if OUTPUT_ALL else 'N/A'
    return '; '.join(numbers)


def format_recovery_phone(result) -> str:
    """Return just the recovery-verified phone number, or N/A."""
    if hasattr(result, 'recovery_check') and result.recovery_check:
        matched = getattr(result.recovery_check, 'matched_number', None)
        if matched:
            return matched
    return 'None' if OUTPUT_ALL else 'N/A'


def format_all_addresses_from_result(result) -> str:
    """Format all addresses, including structured TLO addresses when available."""
    parts: List[str] = []
    if hasattr(result, 'addresses') and result.addresses:
        formatted = format_addresses(result.addresses)
        if formatted not in ('N/A', 'None'):
            parts.append(formatted)
    if TLO_ENRICHMENT and hasattr(result, 'addresses_structured') and result.addresses_structured:
        structured = format_addresses_structured(result.addresses_structured)
        if structured not in ('N/A', 'None') and structured not in parts:
            parts.append(structured)
    if not parts:
        return 'None' if OUTPUT_ALL else 'N/A'
    return ' | '.join(parts)


def format_all_emails_from_result(result) -> str:
    """Format all emails, including TLO other_emails when available."""
    emails: List[str] = []
    seen = set()
    if hasattr(result, 'emails') and result.emails:
        for email in result.emails:
            if email and email not in seen:
                seen.add(email)
                emails.append(email)
    if TLO_ENRICHMENT and hasattr(result, 'other_emails') and result.other_emails:
        for email in result.other_emails:
            if email and email not in seen:
                seen.add(email)
                emails.append(email)
    return format_emails(emails)


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


def format_linkedin(result) -> str:
    """Combine LinkedIn URL and ID into one field."""
    parts = []
    if hasattr(result, 'linkedin_url') and result.linkedin_url:
        parts.append(result.linkedin_url)
    if hasattr(result, 'linkedin_id') and result.linkedin_id:
        parts.append(result.linkedin_id)
    if parts:
        return ' | '.join(parts)
    return 'None' if OUTPUT_ALL else 'N/A'


def build_output_field_values(result, original_input: str, input_field: str = 'email') -> Dict[str, str]:
    """Build all supported output column values (simple names, full API data behind each)."""
    person_info = format_person(result.person) if hasattr(result, 'person') and result.person else {
        'name': 'None' if OUTPUT_ALL else 'N/A',
        'dob': 'None' if OUTPUT_ALL else 'N/A',
        'age': 'None' if OUTPUT_ALL else 'N/A',
        'gender': 'None' if OUTPUT_ALL else 'N/A',
    }
    metadata = format_search_metadata(result)

    values = {
        'email': metadata.get('email', original_input),
        'phone': original_input,
        'name': person_info['name'],
        'dob': person_info['dob'],
        'age': person_info['age'],
        'gender': person_info.get('gender', 'N/A'),
        'phone_numbers': format_all_phones_from_result(result),
        'addresses': format_all_addresses_from_result(result),
        'emails': format_all_emails_from_result(result),
        'recovery_phone': format_recovery_phone(result),
        'companies': metadata.get('companies', 'N/A'),
        'industry': metadata.get('industry', 'N/A'),
        'linkedin': format_linkedin(result),
        'education': metadata.get('education', 'N/A'),
        'location_metro': metadata.get('location_metro', 'N/A'),
        'social_media': metadata.get('social_media_identifiers', 'N/A'),
        'alternative_names': metadata.get('alternative_names', 'N/A'),
        'all_names': metadata.get('all_names', 'N/A'),
        'all_dobs': metadata.get('all_dobs', 'N/A'),
        'related_persons': metadata.get('related_persons', 'N/A'),
        'criminal_records': metadata.get('criminal_records', 'N/A'),
        'total_results': metadata.get('total_results', 'N/A'),
        'search_cost': metadata.get('search_cost', 'N/A'),
        'pricing': metadata.get('pricing_breakdown', 'N/A'),
        'email_valid': metadata.get('email_valid', 'N/A'),
        'email_type': metadata.get('email_type', 'N/A'),
    }
    if input_field == 'phone':
        values['phone'] = original_input
    else:
        values['email'] = metadata.get('email', original_input)
    return values


def create_output_row(result, original_input: str):
    """Build list of output values for configured fields. Returns None if no result and not OUTPUT_ALL."""
    if not result:
        if OUTPUT_ALL:
            return ['None'] * len(get_output_field_order())
        return None

    input_field = 'email' if is_email_mode() else 'phone'
    field_values = build_output_field_values(result, original_input, input_field=input_field)
    return [field_values.get(field, 'N/A') for field in get_output_field_order()]


def create_output_line(result, original_input: str):
    """Create a formatted output line (text or CSV). Returns None if no result and not OUTPUT_ALL."""
    row = create_output_row(result, original_input)
    if row is None:
        return None
    sep = get_output_separator()
    if OUTPUT_FORMAT == 'csv':
        return sep.join(_csv_quote_field(str(v), sep) for v in row)
    return sep.join(row)


def create_output_dict(result, original_input: str):
    """Create a dict of field -> value for JSON output. Returns None if no result and not OUTPUT_ALL."""
    row = create_output_row(result, original_input)
    if row is None:
        return None
    return dict(zip(get_output_field_order(), row))


def format_result_human_readable(result, identifier: str) -> str:
    """Format a result as labeled, human-readable text for live GUI output."""
    labels = get_mode_field_labels()
    input_key = 'email' if is_email_mode() else 'phone'
    input_label = labels.get(input_key, input_key.title())

    if result is None:
        return f"── {input_label}: {identifier} ──\n  No data found\n"

    field_values = build_output_field_values(result, identifier, input_field=input_key)
    lines = [f"── {input_label}: {identifier} ──"]
    for field in get_output_field_order():
        label = labels.get(field, field)
        value = field_values.get(field, 'N/A')
        lines.append(f"  {label}: {value}")
    return "\n".join(lines) + "\n"


def format_error_human_readable(error_line: str) -> str:
    """Format an error line as human-readable text for live GUI output."""
    parts = error_line.split(' | ERROR: ', 1)
    identifier = parts[0].strip()
    err = parts[1].strip() if len(parts) > 1 else error_line
    input_key = 'email' if is_email_mode() else 'phone'
    input_label = get_mode_field_labels().get(input_key, input_key.title())
    return f"── {input_label}: {identifier} ──\n  ERROR: {err}\n"


def _emit_live_output(result, identifier: str) -> None:
    if LIVE_OUTPUT_CALLBACK:
        LIVE_OUTPUT_CALLBACK(format_result_human_readable(result, identifier))


def _emit_live_error(error_line: str) -> None:
    if LIVE_OUTPUT_CALLBACK:
        LIVE_OUTPUT_CALLBACK(format_error_human_readable(error_line))


def write_result_record(f, result, identifier: str) -> None:
    """Write one result record (or empty record when OUTPUT_ALL and result is None). No-op if result is None and not OUTPUT_ALL."""
    if OUTPUT_FORMAT == 'json':
        obj = create_output_dict(result, identifier)
        if obj is not None:
            f.write(json.dumps(obj, ensure_ascii=False) + '\n')
            _emit_live_output(result, identifier)
    else:
        line = create_output_line(result, identifier)
        if line is not None:
            f.write(line + '\n')
            _emit_live_output(result, identifier)


def write_error_record(f, error_line: str) -> None:
    """Write one error line. error_line is the text/csv line; for JSON we parse and write {input_key: ..., error: ...}."""
    input_key = 'email' if is_email_mode() else 'phone'
    if OUTPUT_FORMAT == 'json':
        parts = error_line.split(' | ERROR: ', 1)
        identifier = parts[0].strip()
        err = parts[1].strip() if len(parts) > 1 else error_line
        f.write(json.dumps({input_key: identifier, 'error': err}, ensure_ascii=False) + '\n')
    else:
        f.write(error_line + '\n')
    _emit_live_error(error_line)


def handle_api_error(error: Exception, identifier: str) -> str:
    """Handle different types of API errors and return appropriate error message."""
    invalid_msg = 'Invalid email format' if is_email_mode() else 'Invalid phone number format'
    if isinstance(error, AuthenticationError):
        logger.error(f"Authentication failed for {identifier}: {error}")
        return f"{identifier} | ERROR: Authentication failed - Invalid API key"
    
    elif isinstance(error, InsufficientBalanceError):
        logger.error(f"Insufficient balance for {identifier}: {error}")
        return f"{identifier} | ERROR: Insufficient balance - {error.current_balance if hasattr(error, 'current_balance') else 'Unknown'}"
    
    elif isinstance(error, RateLimitError):
        logger.warning(f"Rate limit exceeded for {identifier}: {error}")
        return f"{identifier} | ERROR: Rate limit exceeded - Please wait before retrying"
    
    elif isinstance(error, ValidationError):
        logger.warning(f"Validation error for {identifier}: {error}")
        return f"{identifier} | ERROR: {invalid_msg}"
    
    elif isinstance(error, TimeoutError):
        logger.warning(f"Timeout for {identifier}: {error}")
        return f"{identifier} | ERROR: Request timeout"
    
    elif isinstance(error, NetworkError):
        logger.warning(f"Network error for {identifier}: {error}")
        return f"{identifier} | ERROR: Network connection error"
    
    elif isinstance(error, ServerError):
        logger.error(f"Server error for {identifier}: {error}")
        return f"{identifier} | ERROR: Server error - {error.status_code if hasattr(error, 'status_code') else 'Unknown'}"
    
    else:
        logger.error(f"Unexpected error for {identifier}: {error}")
        return f"{identifier} | ERROR: Unexpected error - {str(error)}"


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

            if not meets_output_requirements(result):
                logger.debug(
                    f"Skipped {email}: requirements not met ({describe_output_requirements_failure(result)})"
                )
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


def fetch_phone_info(phone: str, output_file: str, api_client: SearchAPI) -> None:
    """Fetch phone information with retries. Writes one row per matching result."""
    for attempt in range(MAX_RETRIES):
        try:
            logger.debug(f"Searching for phone: {phone} (attempt {attempt + 1})")
            results = api_client.search_phone(
                phone=phone,
                house_value=HOUSE_VALUE,
                extra_info=EXTRA_INFO,
                carrier_info=CARRIER_INFO,
                tlo_enrichment=TLO_ENRICHMENT,
                phone_format="international",
            )

            if not results:
                if OUTPUT_ALL:
                    with open(output_file, 'a', encoding=OUTPUT_ENCODING) as f:
                        write_result_record(f, None, phone)
                    logger.debug(f"No result for phone: {phone}")
                return

            written = 0
            with open(output_file, 'a', encoding=OUTPUT_ENCODING) as f:
                for result in results:
                    if not meets_output_requirements(result, tlo_enrichment=TLO_ENRICHMENT, recovery_check=False):
                        logger.debug(
                            f"Skipped result for {phone}: requirements not met "
                            f"({describe_output_requirements_failure(result)})"
                        )
                        continue

                    result_line = create_output_line(result, phone)
                    has_data = OUTPUT_ALL or _result_has_significant_data(result)
                    if result_line and has_data:
                        write_result_record(f, result, phone)
                        written += 1

            if written > 0:
                logger.info(f"Wrote {written} row(s) for phone: {phone}")
            return

        except SearchAPIError as e:
            error_str = str(e)
            if "No data found" in error_str:
                if OUTPUT_ALL:
                    with open(output_file, 'a', encoding=OUTPUT_ENCODING) as f:
                        write_result_record(f, None, phone)
                    logger.debug(f"No data found for: {phone}")
                return
            if "403" in error_str or "Request failed: 403" in error_str:
                logger.warning(f"Rate limited (403) for {phone}: {error_str}")
                if attempt == MAX_RETRIES - 1:
                    with open(output_file, 'a', encoding=OUTPUT_ENCODING) as f:
                        write_error_record(f, f"{phone} | ERROR: Rate limited (403) - Too many requests")
                    return
                import time
                time.sleep((RETRY_DELAY_BASE ** attempt) * 5)
                continue
            if isinstance(e, (AuthenticationError, InsufficientBalanceError, ValidationError)):
                with open(output_file, 'a', encoding=OUTPUT_ENCODING) as f:
                    write_error_record(f, handle_api_error(e, phone))
                return
            if isinstance(e, (RateLimitError, TimeoutError, NetworkError, ServerError)):
                if attempt == MAX_RETRIES - 1:
                    with open(output_file, 'a', encoding=OUTPUT_ENCODING) as f:
                        write_error_record(f, handle_api_error(e, phone))
                    return
                import time
                time.sleep(RETRY_DELAY_BASE ** attempt)
            else:
                if attempt == MAX_RETRIES - 1:
                    with open(output_file, 'a', encoding=OUTPUT_ENCODING) as f:
                        write_error_record(f, f"{phone} | ERROR: Search API error - {error_str}")
                    return
                import time
                time.sleep(RETRY_DELAY_BASE ** attempt)
        except Exception as e:
            logger.error(f"Unexpected error for {phone}: {str(e)}")
            if attempt == MAX_RETRIES - 1:
                with open(output_file, 'a', encoding=OUTPUT_ENCODING) as f:
                    write_error_record(f, f"{phone} | ERROR: Unexpected error - {str(e)}")
            else:
                import time
                time.sleep(RETRY_DELAY_BASE ** attempt)


def _result_has_significant_data(result) -> bool:
    """Return True if result has any meaningful data fields."""
    if hasattr(result, 'phone_numbers') and result.phone_numbers:
        return True
    if hasattr(result, 'addresses') and result.addresses:
        return True
    if hasattr(result, 'person') and result.person and result.person.name:
        return True
    if hasattr(result, 'emails') and result.emails:
        return True
    if TLO_ENRICHMENT:
        for attr in (
            'phone_numbers_full', 'addresses_structured', 'all_names', 'alternative_names',
            'all_dobs', 'related_persons', 'criminal_records', 'censored_numbers',
            'confirmed_numbers', 'other_emails',
        ):
            if getattr(result, attr, None):
                return True
    return False


def prepare_output_file(output_file: str) -> None:
    """Create/truncate the output file and write header if configured."""
    if OUTPUT_FORMAT == 'json':
        open(output_file, 'w', encoding=OUTPUT_ENCODING).close()
    elif INCLUDE_HEADER:
        header = create_header()
        with open(output_file, 'w', encoding=OUTPUT_ENCODING) as f:
            if header:
                f.write(header + '\n')
    else:
        open(output_file, 'w', encoding=OUTPUT_ENCODING).close()


def load_batch_items() -> Tuple[List[str], str, str]:
    """Load input items for the current mode. Returns (items, input_file, output_file)."""
    input_file = get_input_filename()
    output_file = get_output_filename()
    if is_email_mode():
        items = load_emails(input_file)
        if not items:
            raise ValueError(f"No valid emails found in {input_file}")
    else:
        items = load_phones(input_file)
        if not items:
            raise ValueError(f"No valid phone numbers found in {input_file}")
    return items, input_file, output_file


def log_batch_start(items: List[str], input_file: str) -> None:
    """Log configuration summary at batch start."""
    logger.info(f"Starting {SEARCH_MODE} search with {len(items)} items from {input_file}")
    logger.info(
        f"Configuration: HOUSE_VALUE={HOUSE_VALUE}, EXTRA_INFO={EXTRA_INFO}, "
        f"CARRIER_INFO={CARRIER_INFO}, TLO_ENRICHMENT={TLO_ENRICHMENT}, RECOVERY_CHECK={RECOVERY_CHECK}"
    )
    logger.info(f"Output fields: {', '.join(get_output_field_order())}")
    if OUTPUT_REQUIREMENTS:
        logger.info(f"Output requirements: {format_output_requirements()}")
    if RECOVERY_MODULES and is_email_mode():
        logger.info(
            f"Recovery modules: order={RECOVERY_MODULES.get('module_order')}, "
            f"enabled={RECOVERY_MODULES.get('enabled_modules')}"
        )


def fetch_available_recovery_modules(api_key_value: str) -> List[Dict[str, Any]]:
    """Fetch recovery module list from the API for GUI/CLI configuration."""
    if not api_key_value:
        return []
    config = SearchAPIConfig(api_key=api_key_value, debug_mode=False)
    client = SearchAPI(config=config)
    try:
        response = client.get_recovery_modules()
        modules: List[Dict[str, Any]] = []
        for module in response.modules:
            price = module.price
            if not price and response.pricing:
                price = response.pricing.get(module.module_name, 0.0)
            modules.append({
                'module_name': module.module_name,
                'display_name': module.display_name or module.module_name,
                'price': float(price or 0),
                'description': module.description or '',
            })
        return modules
    finally:
        try:
            client.close()
        except Exception:
            pass


def merge_recovery_module_selection(
    available_modules: List[Dict[str, Any]],
    saved: Optional[Dict[str, List[str]]] = None,
) -> Tuple[List[str], Set[str]]:
    """
    Merge API module list with saved config.
    Returns (module_order, enabled_module_names).
    """
    names = [m['module_name'] for m in available_modules]
    if not names:
        return [], set()

    saved = saved or {}
    saved_order = saved.get('module_order') or []
    saved_enabled = saved.get('enabled_modules')

    order = [name for name in saved_order if name in names]
    order.extend(name for name in names if name not in order)

    if saved_enabled is None:
        enabled = set(names)
    else:
        enabled = {name for name in saved_enabled if name in names}
        if not enabled:
            enabled = set(names)
    return order, enabled


def build_recovery_modules_config(module_order: List[str], enabled_modules: List[str]) -> Dict[str, List[str]]:
    """Build recovery_modules dict for search_email."""
    enabled_set = set(enabled_modules)
    order = list(module_order)
    for name in enabled_modules:
        if name not in order:
            order.append(name)
    return {
        'module_order': order,
        'enabled_modules': [name for name in order if name in enabled_set],
    }


def parse_cli_mode() -> None:
    """Apply --mode email|phone from command line if present."""
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == '--mode' and i + 1 < len(args):
            set_search_mode(args[i + 1].lower())
            return
        if arg.startswith('--mode='):
            set_search_mode(arg.split('=', 1)[1].lower())
            return


def run_batch(items: List[str], output_file: str) -> None:
    """Process emails or phones based on SEARCH_MODE."""
    if not api_key:
        logger.error("API key is required. Please set the api_key variable.")
        return

    item_label = 'emails' if is_email_mode() else 'phones'
    fetch_fn = fetch_email_info if is_email_mode() else fetch_phone_info

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
            estimated_cost = len(items) * (base_cost + feature_costs)
            if balance_info.current_balance < estimated_cost:
                logger.warning(
                    f"Insufficient balance for all searches. "
                    f"Current: ${balance_info.current_balance}, Estimated needed: ${estimated_cost}"
                )
        except Exception as e:
            logger.warning(f"Could not check balance: {e}")

        logger.info(f"Starting to process {len(items)} {item_label} with {MAX_WORKERS} workers (mode: {SEARCH_MODE})")
        logger.info(f"Output fields: {', '.join(get_output_field_order())}")
        if OUTPUT_REQUIREMENTS:
            logger.info(f"Output requirements: {format_output_requirements()}")
        logger.info(f"Connection pool: max {CONNECTION_POOL_MAXSIZE} connections per host")

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_item = {
                executor.submit(fetch_fn, item, output_file, api_client): item
                for item in items
            }
            completed = 0
            for future in as_completed(future_to_item):
                item = future_to_item[future]
                completed += 1
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Task failed for {item}: {e}")
                if ON_PROGRESS_CALLBACK:
                    ON_PROGRESS_CALLBACK(completed, len(items), item)
                if completed % 25 == 0 or completed == len(items):
                    logger.info(f"Progress: {completed}/{len(items)} {item_label} processed")

        logger.info("Processing complete!")

    except Exception as e:
        logger.error(f"Fatal error in run_batch: {str(e)}")
        traceback.print_exc()
    finally:
        try:
            api_client.close()
        except Exception:
            pass


def main(emails: List[str], output_file: str) -> None:
    """Backward-compatible alias for email batch processing."""
    run_batch(emails, output_file)




# =============================================================================
# GUI — settings window and live processing output
# =============================================================================

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, scrolledtext
except ImportError:  # pragma: no cover
    tk = None
    ttk = messagebox = scrolledtext = None


BRAND = {
    'primary': '#2563eb',
    'primary_dark': '#1d4ed8',
    'primary_light': '#3b82f6',
    'purple': '#8b5cf6',
    'bg': '#f8fafc',
    'card': '#ffffff',
    'text': '#0f172a',
    'muted': '#64748b',
    'border': '#e2e8f0',
    'success': '#10b981',
    'header': '#0f172a',
}

FONT = ('Segoe UI', 10)
FONT_BOLD = ('Segoe UI', 10, 'bold')
FONT_TITLE = ('Segoe UI', 18, 'bold')
FONT_SUB = ('Segoe UI', 11)
FONT_SMALL = ('Segoe UI', 9)

EXTRA_OUTPUT_FIELDS: List[tuple] = [
    ('gender', 'Gender'),
    ('companies', 'Companies'),
    ('industry', 'Industry'),
    ('linkedin', 'LinkedIn'),
    ('education', 'Education'),
    ('location_metro', 'Metro area'),
    ('social_media', 'Social media'),
    ('alternative_names', 'Alt names'),
    ('all_names', 'All names'),
    ('all_dobs', 'All DOBs'),
    ('related_persons', 'Related people'),
    ('criminal_records', 'Criminal records'),
    ('total_results', 'Result count'),
    ('search_cost', 'Cost'),
    ('pricing', 'Pricing breakdown'),
    ('email_valid', 'Email valid'),
    ('email_type', 'Email type'),
]

EMAIL_ONLY_EXTRA = frozenset({'email_valid', 'email_type'})


def _apply_brand_theme(root: tk.Tk) -> ttk.Style:
    root.configure(bg=BRAND['bg'])
    style = ttk.Style(root)
    try:
        style.theme_use('clam')
    except tk.TclError:
        pass

    style.configure('.', background=BRAND['bg'], foreground=BRAND['text'], font=FONT)
    style.configure('TFrame', background=BRAND['bg'])
    style.configure('Card.TFrame', background=BRAND['card'])
    style.configure('TLabel', background=BRAND['bg'], foreground=BRAND['text'], font=FONT)
    style.configure('Card.TLabel', background=BRAND['card'], foreground=BRAND['text'], font=FONT)
    style.configure('Muted.TLabel', background=BRAND['card'], foreground=BRAND['muted'], font=FONT_SMALL)
    style.configure('Header.TLabel', background=BRAND['header'], foreground='#ffffff', font=FONT_SUB)
    style.configure('Title.TLabel', background=BRAND['header'], foreground='#ffffff', font=FONT_TITLE)
    style.configure('CardTitle.TLabel', background=BRAND['card'], foreground=BRAND['text'], font=FONT_BOLD)

    style.configure(
        'Card.TLabelframe',
        background=BRAND['card'],
        bordercolor=BRAND['border'],
        relief='solid',
        borderwidth=1,
    )
    style.configure(
        'Card.TLabelframe.Label',
        background=BRAND['card'],
        foreground=BRAND['text'],
        font=FONT_BOLD,
    )
    style.configure('TCheckbutton', background=BRAND['card'], foreground=BRAND['text'], font=FONT)
    style.configure('TRadiobutton', background=BRAND['card'], foreground=BRAND['text'], font=FONT)
    style.configure('TEntry', fieldbackground='#ffffff', foreground=BRAND['text'], bordercolor=BRAND['border'])

    style.configure(
        'Primary.TButton',
        background=BRAND['primary'],
        foreground='#ffffff',
        borderwidth=0,
        focusthickness=0,
        font=FONT_BOLD,
        padding=(16, 10),
    )
    style.map(
        'Primary.TButton',
        background=[('active', BRAND['primary_dark']), ('pressed', BRAND['primary_dark'])],
        foreground=[('disabled', '#94a3b8')],
    )
    style.configure(
        'Secondary.TButton',
        background=BRAND['card'],
        foreground=BRAND['text'],
        borderwidth=1,
        font=FONT,
        padding=(14, 9),
    )
    style.map(
        'Secondary.TButton',
        background=[('active', BRAND['bg'])],
    )
    return style


def _draw_logo(canvas: tk.Canvas, x: int, y: int, size: int = 36) -> None:
    canvas.create_rectangle(
        x, y, x + size, y + size,
        fill=BRAND['primary'], outline=BRAND['primary_dark'], width=0,
    )
    cx, cy = x + size / 2, y + size / 2
    r = size * 0.32
    pts = []
    for i in range(6):
        ang = math.pi / 2 + i * math.pi / 3
        pts.extend([cx + r * 1.15 * math.cos(ang), cy + r * 1.15 * math.sin(ang)])
    canvas.create_polygon(pts, outline='#ffffff', fill='', width=2)
    inner = []
    for i in range(6):
        ang = math.pi / 2 + i * math.pi / 3
        inner.extend([cx + r * 0.55 * math.cos(ang), cy + r * 0.55 * math.sin(ang)])
    canvas.create_polygon(inner, fill='#ffffff', outline='')


class SearchConfigApp(tk.Tk):
    def __init__(self, run_after_save: bool = False):
        super().__init__()
        self.run_after_save = run_after_save
        self.title('SearchAPI — Batch Search Settings')
        self.geometry('580x880')
        self.minsize(520, 700)
        self.configure(bg=BRAND['bg'])

        _apply_brand_theme(self)
        load_config()

        self.output_vars: Dict[str, tk.BooleanVar] = {}
        self.requirement_vars: Dict[str, tk.BooleanVar] = {}
        self.preset_var = tk.StringVar(value='default')
        self.mode_var = tk.StringVar(value=SEARCH_MODE)
        self._building_preset = False
        self._mode_changing = False

        self.subtitle_label = None
        self.input_hint_label = None
        self.recovery_check_btn = None
        self.recovery_section_frame = None
        self.recovery_status_label = None
        self.recovery_modules_frame = None
        self.recovery_module_order: List[str] = []
        self.recovery_module_info: Dict[str, dict] = {}
        self.recovery_enabled_vars: Dict[str, tk.BooleanVar] = {}
        self._recovery_fetching = False
        self.simple_checkbuttons: Dict[str, tk.Checkbutton] = {}
        self.req_checkbuttons: Dict[str, tk.Checkbutton] = {}
        self.extra_checkbuttons: Dict[str, tk.Checkbutton] = {}

        self._build_ui()
        self._load_from_config()

    def _card(self, parent, title: str) -> tuple:
        wrapper = ttk.Frame(parent, style='Card.TFrame', padding=0)
        wrapper.pack(fill=tk.X, pady=(0, 14))

        inner = tk.Frame(wrapper, bg=BRAND['card'], highlightbackground=BRAND['border'], highlightthickness=1)
        inner.pack(fill=tk.X, padx=0, pady=0)

        head = tk.Frame(inner, bg=BRAND['card'])
        head.pack(fill=tk.X, padx=16, pady=(14, 8))
        tk.Label(head, text=title, font=FONT_BOLD, fg=BRAND['text'], bg=BRAND['card']).pack(anchor=tk.W)

        body = tk.Frame(inner, bg=BRAND['card'])
        body.pack(fill=tk.X, padx=16, pady=(0, 14))
        return body, wrapper

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=BRAND['header'], height=88)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        header_inner = tk.Frame(header, bg=BRAND['header'])
        header_inner.pack(fill=tk.BOTH, expand=True, padx=20, pady=16)

        logo_canvas = tk.Canvas(header_inner, width=40, height=40, bg=BRAND['header'], highlightthickness=0)
        logo_canvas.pack(side=tk.LEFT)
        _draw_logo(logo_canvas, 2, 2, 36)

        title_block = tk.Frame(header_inner, bg=BRAND['header'])
        title_block.pack(side=tk.LEFT, padx=(12, 0))
        tk.Label(title_block, text='SearchAPI', font=FONT_TITLE, fg='#ffffff', bg=BRAND['header']).pack(anchor=tk.W)
        self.subtitle_label = tk.Label(
            title_block,
            text='Batch search · Enterprise data enrichment',
            font=FONT_SMALL,
            fg='#94a3b8',
            bg=BRAND['header'],
        )
        self.subtitle_label.pack(anchor=tk.W)

        site_link = tk.Label(
            header_inner,
            text='search-api.dev',
            font=FONT_SMALL,
            fg=BRAND['primary_light'],
            bg=BRAND['header'],
            cursor='hand2',
        )
        site_link.pack(side=tk.RIGHT)
        site_link.bind('<Button-1>', lambda e: webbrowser.open('https://search-api.dev/'))

        outer = ttk.Frame(self, padding=(16, 12, 16, 0))
        outer.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(outer, highlightthickness=0, bg=BRAND['bg'], bd=0)
        scrollbar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=self.canvas.yview)
        self.body = tk.Frame(self.canvas, bg=BRAND['bg'])

        self.body.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self._canvas_window = self.canvas.create_window((0, 0), window=self.body, anchor='nw')
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.bind('<Configure>', self._on_canvas_resize)
        self.canvas.bind_all('<MouseWheel>', self._on_mousewheel)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # What to process
        mode_body, _ = self._card(self.body, 'What are you processing?')
        mode_row = tk.Frame(mode_body, bg=BRAND['card'])
        mode_row.pack(fill=tk.X, pady=(0, 6))
        for val, label in (('email', 'Email search'), ('phone', 'Phone search')):
            tk.Radiobutton(
                mode_row, text=label, value=val, variable=self.mode_var,
                command=self._on_mode_changed, font=FONT, fg=BRAND['text'], bg=BRAND['card'],
                activebackground=BRAND['card'], selectcolor=BRAND['primary_light'],
            ).pack(side=tk.LEFT, padx=(0, 24))
        self.input_hint_label = tk.Label(
            mode_body,
            text='Input file: emails.txt  →  output.txt',
            font=FONT_SMALL, fg=BRAND['muted'], bg=BRAND['card'],
        )
        self.input_hint_label.pack(anchor=tk.W)

        key_body, _ = self._card(self.body, 'API key')
        tk.Label(key_body, text='Your SearchAPI key from the dashboard', font=FONT_SMALL, fg=BRAND['muted'], bg=BRAND['card']).pack(anchor=tk.W, pady=(0, 6))
        self.api_key_var = tk.StringVar(value=api_key)
        key_entry = tk.Entry(
            key_body, textvariable=self.api_key_var, font=FONT,
            relief='solid', bd=1, highlightthickness=1,
            highlightbackground=BRAND['border'], highlightcolor=BRAND['primary'],
        )
        key_entry.pack(fill=tk.X, ipady=6)

        opts_body, _ = self._card(self.body, 'Search options')
        self.opt_vars = {
            'house_value': tk.BooleanVar(value=HOUSE_VALUE),
            'extra_info': tk.BooleanVar(value=EXTRA_INFO),
            'carrier_info': tk.BooleanVar(value=CARRIER_INFO),
            'tlo_enrichment': tk.BooleanVar(value=TLO_ENRICHMENT),
            'recovery_check': tk.BooleanVar(value=RECOVERY_CHECK),
            'output_all': tk.BooleanVar(value=OUTPUT_ALL),
        }
        options = [
            ('house_value', 'House value (Zestimate)  +$0.0015'),
            ('extra_info', 'Extra info enrichment  +$0.0015'),
            ('carrier_info', 'Carrier info  +$0.0005'),
            ('tlo_enrichment', 'TLO enrichment  +$0.0025'),
            ('recovery_check', 'Recovery phone verification'),
            ('output_all', 'Include empty / not-found lines'),
        ]
        self.opt_checkbuttons: Dict[str, tk.Checkbutton] = {}
        for key, label in options:
            btn = tk.Checkbutton(
                opts_body, text=label, variable=self.opt_vars[key],
                command=self._on_recovery_check_changed if key == 'recovery_check' else None,
                font=FONT, fg=BRAND['text'], bg=BRAND['card'],
                activebackground=BRAND['card'], selectcolor=BRAND['card'],
            )
            btn.pack(anchor=tk.W, pady=2)
            self.opt_checkbuttons[key] = btn
            if key == 'recovery_check':
                self.recovery_check_btn = btn

        self.recovery_section_frame = tk.Frame(opts_body, bg=BRAND['card'])
        tk.Frame(self.recovery_section_frame, bg=BRAND['border'], height=1).pack(fill=tk.X, pady=(10, 12))
        tk.Label(
            self.recovery_section_frame, text='Recovery modules', font=FONT_BOLD,
            fg=BRAND['text'], bg=BRAND['card'],
        ).pack(anchor=tk.W)
        tk.Label(
            self.recovery_section_frame,
            text='Pick which modules to run and set the order they are tried (top first).',
            font=FONT_SMALL, fg=BRAND['muted'], bg=BRAND['card'], wraplength=520, justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(4, 8))

        recovery_toolbar = tk.Frame(self.recovery_section_frame, bg=BRAND['card'])
        recovery_toolbar.pack(fill=tk.X, pady=(0, 8))
        self.recovery_status_label = tk.Label(
            recovery_toolbar, text='', font=FONT_SMALL, fg=BRAND['muted'], bg=BRAND['card'],
        )
        self.recovery_status_label.pack(side=tk.LEFT)
        ttk.Button(
            recovery_toolbar, text='Refresh modules', style='Secondary.TButton',
            command=self._fetch_recovery_modules,
        ).pack(side=tk.RIGHT)

        self.recovery_modules_frame = tk.Frame(self.recovery_section_frame, bg=BRAND['card'])
        self.recovery_modules_frame.pack(fill=tk.X)

        out_body, _ = self._card(self.body, 'Output columns')
        tk.Label(out_body, text='Quick preset', font=FONT_SMALL, fg=BRAND['muted'], bg=BRAND['card']).pack(anchor=tk.W)
        preset_row = tk.Frame(out_body, bg=BRAND['card'])
        preset_row.pack(fill=tk.X, pady=(4, 10))
        for key, label in (('default', 'Basic'), ('phones', 'Phones'), ('contact', 'Contact'), ('full', 'All')):
            tk.Radiobutton(
                preset_row, text=label, value=key, variable=self.preset_var,
                command=self._apply_preset, font=FONT, fg=BRAND['text'], bg=BRAND['card'],
                activebackground=BRAND['card'], selectcolor=BRAND['primary_light'],
            ).pack(side=tk.LEFT, padx=(0, 16))

        tk.Label(out_body, text='Columns to include', font=FONT_SMALL, fg=BRAND['muted'], bg=BRAND['card']).pack(anchor=tk.W, pady=(4, 4))
        self.cols = tk.Frame(out_body, bg=BRAND['card'])
        self.cols.pack(fill=tk.X)

        all_simple = SIMPLE_OUTPUT_FIELDS_EMAIL + [
            (k, l) for k, l in SIMPLE_OUTPUT_FIELDS_PHONE if k not in {x[0] for x in SIMPLE_OUTPUT_FIELDS_EMAIL}
        ]
        for i, (key, label) in enumerate(all_simple):
            var = tk.BooleanVar()
            self.output_vars[key] = var
            btn = tk.Checkbutton(
                self.cols, text=label, variable=var, command=self._on_output_changed,
                font=FONT, fg=BRAND['text'], bg=BRAND['card'],
                activebackground=BRAND['card'], selectcolor=BRAND['card'],
            )
            btn.grid(row=i // 2, column=i % 2, sticky=tk.W, padx=(0, 20), pady=2)
            self.simple_checkbuttons[key] = btn

        self.more_visible = tk.BooleanVar(value=False)
        tk.Checkbutton(
            out_body, text='More columns…', variable=self.more_visible, command=self._toggle_more,
            font=FONT, fg=BRAND['primary'], bg=BRAND['card'],
            activebackground=BRAND['card'], selectcolor=BRAND['card'],
        ).pack(anchor=tk.W, pady=(8, 0))
        self.more_frame = tk.Frame(out_body, bg=BRAND['card'])
        for i, (key, label) in enumerate(EXTRA_OUTPUT_FIELDS):
            var = tk.BooleanVar()
            self.output_vars[key] = var
            btn = tk.Checkbutton(
                self.more_frame, text=label, variable=var, command=self._on_output_changed,
                font=FONT, fg=BRAND['text'], bg=BRAND['card'],
                activebackground=BRAND['card'], selectcolor=BRAND['card'],
            )
            btn.grid(row=i // 2, column=i % 2, sticky=tk.W, padx=(0, 20), pady=2)
            self.extra_checkbuttons[key] = btn

        req_body, _ = self._card(self.body, 'Only output if result has…')
        tk.Label(
            req_body,
            text='Rows missing any checked item below will be skipped.',
            font=FONT_SMALL, fg=BRAND['muted'], bg=BRAND['card'],
        ).pack(anchor=tk.W, pady=(0, 6))
        self.req_cols = tk.Frame(req_body, bg=BRAND['card'])
        self.req_cols.pack(fill=tk.X)
        all_req = REQUIREMENT_FIELDS_EMAIL + [
            (k, l) for k, l in REQUIREMENT_FIELDS_PHONE if k not in {x[0] for x in REQUIREMENT_FIELDS_EMAIL}
        ]
        for i, (key, label) in enumerate(all_req):
            var = tk.BooleanVar()
            self.requirement_vars[key] = var
            btn = tk.Checkbutton(
                self.req_cols, text=label, variable=var,
                font=FONT, fg=BRAND['text'], bg=BRAND['card'],
                activebackground=BRAND['card'], selectcolor=BRAND['card'],
            )
            btn.grid(row=i // 2, column=i % 2, sticky=tk.W, padx=(0, 20), pady=2)
            self.req_checkbuttons[key] = btn

        fmt_body, _ = self._card(self.body, 'Output format')
        self.format_var = tk.StringVar(value=OUTPUT_FORMAT)
        for val, label in (('text', 'Text (pipe-separated)'), ('csv', 'CSV'), ('json', 'JSON')):
            tk.Radiobutton(
                fmt_body, text=label, value=val, variable=self.format_var,
                font=FONT, fg=BRAND['text'], bg=BRAND['card'],
                activebackground=BRAND['card'], selectcolor=BRAND['primary_light'],
            ).pack(anchor=tk.W, pady=2)

        footer = tk.Frame(self, bg=BRAND['bg'], pady=12, padx=16)
        footer.pack(fill=tk.X, side=tk.BOTTOM)

        ttk.Button(footer, text='Save settings', style='Secondary.TButton', command=self._save).pack(side=tk.LEFT)
        ttk.Button(footer, text='Save & run search', style='Primary.TButton', command=self._save_and_run).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(footer, text='Cancel', style='Secondary.TButton', command=self.destroy).pack(side=tk.RIGHT)

        self._refresh_mode_ui()

    def _current_mode(self) -> str:
        return self.mode_var.get() if self.mode_var.get() in ('email', 'phone') else 'email'

    def _refresh_mode_ui(self) -> None:
        mode = self._current_mode()
        is_email = mode == 'email'
        self.subtitle_label.config(
            text='Batch email search · Enterprise data enrichment' if is_email
            else 'Batch phone search · Enterprise data enrichment'
        )
        self.input_hint_label.config(
            text=f"Input file: {get_input_filename(mode)}  →  {get_output_filename(mode)}"
        )
        if self.recovery_check_btn:
            if is_email:
                self.recovery_check_btn.pack(anchor=tk.W, pady=2)
            else:
                self.recovery_check_btn.pack_forget()
                self.opt_vars['recovery_check'].set(False)

        simple_keys = {k for k, _ in get_mode_simple_fields(mode)}
        for key, btn in self.simple_checkbuttons.items():
            if key in simple_keys:
                btn.grid()
            else:
                btn.grid_remove()

        req_keys = {k for k, _ in get_mode_requirement_fields(mode)}
        for key, btn in self.req_checkbuttons.items():
            if key in req_keys:
                btn.grid()
            else:
                btn.grid_remove()

        for key, btn in self.extra_checkbuttons.items():
            if not is_email and key in EMAIL_ONLY_EXTRA:
                btn.grid_remove()
            else:
                btn.grid()

        self._refresh_recovery_section()

    def _recovery_visible(self) -> bool:
        return self._current_mode() == 'email' and self.opt_vars['recovery_check'].get()

    def _refresh_recovery_section(self) -> None:
        if not self.recovery_section_frame:
            return
        if self._recovery_visible():
            self.recovery_section_frame.pack(fill=tk.X, pady=(0, 4))
        else:
            self.recovery_section_frame.pack_forget()

    def _ensure_recovery_phone_column(self) -> None:
        """Check recovery_phone in output columns when recovery verification is enabled."""
        if not self.opt_vars['recovery_check'].get() or self._current_mode() != 'email':
            return
        var = self.output_vars.get('recovery_phone')
        if var and not var.get():
            self._building_preset = True
            var.set(True)
            self._building_preset = False
            self.preset_var.set('')

    def _on_recovery_check_changed(self) -> None:
        self._ensure_recovery_phone_column()
        self._refresh_recovery_section()
        if self._recovery_visible():
            self._fetch_recovery_modules()

    def _fetch_recovery_modules(self) -> None:
        if self._recovery_fetching:
            return
        api_key = self.api_key_var.get().strip()
        if not api_key:
            self.recovery_status_label.config(text='Enter an API key above to load modules.')
            return
        self._recovery_fetching = True
        self.recovery_status_label.config(text='Loading modules…')

        def worker() -> None:
            error = None
            modules = []
            try:
                modules = fetch_available_recovery_modules(api_key)
            except Exception as exc:
                error = str(exc)
            self.after(0, lambda: self._on_recovery_modules_loaded(modules, error))

        threading.Thread(target=worker, daemon=True).start()

    def _on_recovery_modules_loaded(self, modules: List[dict], error: str = None) -> None:
        self._recovery_fetching = False
        if error:
            self.recovery_status_label.config(text=f'Could not load modules: {error}')
            return
        if not modules:
            self.recovery_status_label.config(text='No recovery modules returned by the API.')
            self.recovery_module_order.clear()
            self.recovery_module_info.clear()
            self._render_recovery_module_rows()
            return

        self.recovery_module_info = {m['module_name']: m for m in modules}
        order, enabled = merge_recovery_module_selection(modules, RECOVERY_MODULES)
        self.recovery_module_order = order

        for name in order:
            if name not in self.recovery_enabled_vars:
                self.recovery_enabled_vars[name] = tk.BooleanVar(value=name in enabled)
            else:
                self.recovery_enabled_vars[name].set(name in enabled)

        self._render_recovery_module_rows()
        enabled_count = sum(1 for name in order if self.recovery_enabled_vars[name].get())
        self.recovery_status_label.config(
            text=f'{len(order)} modules · {enabled_count} enabled · order is top → bottom'
        )

    def _render_recovery_module_rows(self) -> None:
        for widget in self.recovery_modules_frame.winfo_children():
            widget.destroy()

        if not self.recovery_module_order:
            tk.Label(
                self.recovery_modules_frame,
                text='No modules loaded yet.',
                font=FONT_SMALL, fg=BRAND['muted'], bg=BRAND['card'],
            ).pack(anchor=tk.W)
            return

        for index, name in enumerate(self.recovery_module_order):
            info = self.recovery_module_info.get(name, {})
            row = tk.Frame(self.recovery_modules_frame, bg=BRAND['card'])
            row.pack(fill=tk.X, pady=3)

            enabled_var = self.recovery_enabled_vars.setdefault(name, tk.BooleanVar(value=True))
            tk.Checkbutton(
                row, variable=enabled_var, font=FONT, fg=BRAND['text'], bg=BRAND['card'],
                activebackground=BRAND['card'], selectcolor=BRAND['card'],
            ).pack(side=tk.LEFT)

            display = info.get('display_name', name)
            price = info.get('price', 0)
            desc = info.get('description', '')
            label_text = f'{index + 1}. {display}  (+${price:.4f})'
            tk.Label(
                row, text=label_text, font=FONT, fg=BRAND['text'], bg=BRAND['card'],
            ).pack(side=tk.LEFT, padx=(4, 8))
            if desc:
                tk.Label(
                    row, text=desc, font=FONT_SMALL, fg=BRAND['muted'], bg=BRAND['card'],
                ).pack(side=tk.LEFT)

            controls = tk.Frame(row, bg=BRAND['card'])
            controls.pack(side=tk.RIGHT)
            up_state = tk.NORMAL if index > 0 else tk.DISABLED
            down_state = tk.NORMAL if index < len(self.recovery_module_order) - 1 else tk.DISABLED
            tk.Button(
                controls, text='↑', width=2, font=FONT_SMALL, relief='solid', bd=1,
                command=lambda n=name: self._move_recovery_module(n, -1), state=up_state,
            ).pack(side=tk.LEFT, padx=1)
            tk.Button(
                controls, text='↓', width=2, font=FONT_SMALL, relief='solid', bd=1,
                command=lambda n=name: self._move_recovery_module(n, 1), state=down_state,
            ).pack(side=tk.LEFT, padx=1)

    def _move_recovery_module(self, name: str, direction: int) -> None:
        try:
            index = self.recovery_module_order.index(name)
        except ValueError:
            return
        new_index = index + direction
        if new_index < 0 or new_index >= len(self.recovery_module_order):
            return
        order = list(self.recovery_module_order)
        order[index], order[new_index] = order[new_index], order[index]
        self.recovery_module_order = order
        self._render_recovery_module_rows()
        enabled_count = sum(
            1 for module_name in order if self.recovery_enabled_vars[module_name].get()
        )
        self.recovery_status_label.config(
            text=f'{len(order)} modules · {enabled_count} enabled · order is top → bottom'
        )

    def _collect_recovery_modules(self) -> dict:
        if not self._recovery_visible():
            return None
        if not self.recovery_module_order:
            raise ValueError('Recovery is enabled but no modules are loaded. Click Refresh modules.')
        enabled = [
            name for name in self.recovery_module_order
            if self.recovery_enabled_vars.get(name) and self.recovery_enabled_vars[name].get()
        ]
        if not enabled:
            raise ValueError('Enable at least one recovery module.')
        return build_recovery_modules_config(self.recovery_module_order, enabled)

    def _persist_current_mode_to_cfg(self) -> None:
        global api_key, HOUSE_VALUE, EXTRA_INFO, CARRIER_INFO, TLO_ENRICHMENT
        global RECOVERY_CHECK, RECOVERY_MODULES, OUTPUT_ALL, OUTPUT_FORMAT
        api_key = self.api_key_var.get().strip()
        HOUSE_VALUE = self.opt_vars['house_value'].get()
        EXTRA_INFO = self.opt_vars['extra_info'].get()
        CARRIER_INFO = self.opt_vars['carrier_info'].get()
        TLO_ENRICHMENT = self.opt_vars['tlo_enrichment'].get()
        RECOVERY_CHECK = self.opt_vars['recovery_check'].get() if self._current_mode() == 'email' else False
        if self._recovery_visible() and self.recovery_module_order:
            enabled = [
                name for name in self.recovery_module_order
                if self.recovery_enabled_vars.get(name) and self.recovery_enabled_vars[name].get()
            ]
            if enabled:
                RECOVERY_MODULES = build_recovery_modules_config(
                    self.recovery_module_order, enabled
                )
        OUTPUT_ALL = self.opt_vars['output_all'].get()
        OUTPUT_FORMAT = self.format_var.get()
        selected = self._collect_output_fields()
        if selected:
            apply_output_field_selection(selected)
        OUTPUT_REQUIREMENTS.clear()
        req_keys = {k for k, _ in get_mode_requirement_fields()}
        for key, var in self.requirement_vars.items():
            if key in req_keys and var.get():
                OUTPUT_REQUIREMENTS.append(key)

    def _on_mode_changed(self) -> None:
        if self._mode_changing:
            return
        self._mode_changing = True
        try:
            self._persist_current_mode_to_cfg()
            set_search_mode(self._current_mode())
            self._refresh_mode_ui()
            self._load_from_config()
        finally:
            self._mode_changing = False

    def _on_canvas_resize(self, event) -> None:
        self.body.winfo_toplevel().update_idletasks()
        canvas = event.widget
        canvas.itemconfig(self._canvas_window, width=event.width)

    def _on_mousewheel(self, event) -> None:
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')

    def _toggle_more(self) -> None:
        if self.more_visible.get():
            self.more_frame.pack(fill=tk.X, pady=(6, 0))
        else:
            self.more_frame.pack_forget()

    def _apply_preset(self) -> None:
        preset = self.preset_var.get()
        fields = get_mode_presets().get(preset, OUTPUT_FIELDS)
        self._building_preset = True
        for key, var in self.output_vars.items():
            var.set(key in fields)
        self._building_preset = False

    def _on_output_changed(self) -> None:
        if self._building_preset:
            return
        self.preset_var.set('')

    def _detect_preset(self, fields: Set[str]) -> str:
        for name, preset_fields in get_mode_presets().items():
            if set(preset_fields) == fields:
                return name
        return ''

    def _load_from_config(self) -> None:
        self.mode_var.set(SEARCH_MODE)
        self.api_key_var.set(api_key)
        self.opt_vars['house_value'].set(HOUSE_VALUE)
        self.opt_vars['extra_info'].set(EXTRA_INFO)
        self.opt_vars['carrier_info'].set(CARRIER_INFO)
        self.opt_vars['tlo_enrichment'].set(TLO_ENRICHMENT)
        self.opt_vars['recovery_check'].set(RECOVERY_CHECK)
        self.opt_vars['output_all'].set(OUTPUT_ALL)

        enabled = set(get_enabled_output_fields())
        extra_visible = any(key in enabled for key, _ in EXTRA_OUTPUT_FIELDS)
        if extra_visible:
            self.more_visible.set(True)
            self._toggle_more()

        self._building_preset = True
        for key, var in self.output_vars.items():
            var.set(key in enabled)
        self._building_preset = False

        self.preset_var.set(self._detect_preset(enabled) or 'default')

        req_keys = {k for k, _ in get_mode_requirement_fields()}
        for key, var in self.requirement_vars.items():
            var.set(key in OUTPUT_REQUIREMENTS and key in req_keys)

        self.format_var.set(OUTPUT_FORMAT)
        self._refresh_mode_ui()
        if self._recovery_visible():
            self._ensure_recovery_phone_column()
            self._fetch_recovery_modules()

    def _collect_output_fields(self) -> List[str]:
        mode = self._current_mode()
        simple = [k for k, _ in get_mode_simple_fields(mode)]
        extra = [k for k, _ in EXTRA_OUTPUT_FIELDS if not (mode == 'phone' and k in EMAIL_ONLY_EXTRA)]
        order = simple + extra
        return [key for key in order if self.output_vars.get(key) and self.output_vars[key].get()]

    def _save_to_module(self) -> None:
        global RECOVERY_MODULES
        set_search_mode(self._current_mode())
        self._persist_current_mode_to_cfg()
        if not api_key:
            raise ValueError('API key is required.')
        self._ensure_recovery_phone_column()
        if self._recovery_visible():
            RECOVERY_MODULES = self._collect_recovery_modules()
        selected = self._collect_output_fields()
        if not selected:
            raise ValueError('Pick at least one output column.')
        apply_output_field_selection(selected)
        ensure_recovery_phone_output_field()
        save_config()

    def _save(self) -> None:
        try:
            self._save_to_module()
        except ValueError as e:
            messagebox.showerror('SearchAPI', str(e))
            return
        messagebox.showinfo('SearchAPI', f'Settings saved.\n{CONFIG_PATH}')

    def _save_and_run(self) -> None:
        try:
            self._save_to_module()
        except ValueError as e:
            messagebox.showerror('SearchAPI', str(e))
            return
        self.run_after_save = True
        self._launch_live_search()

    def _launch_live_search(self) -> None:
        """Hide settings and open the live results window (same Tk main loop)."""
        try:
            items, input_file, output_file = load_batch_items()
        except FileNotFoundError:
            messagebox.showerror(
                'SearchAPI',
                f'{get_input_filename()} not found.\n'
                f'Create a file with one {"email" if is_email_mode() else "phone number"} per line.',
            )
            return
        except ValueError as e:
            messagebox.showerror('SearchAPI', str(e))
            return

        prepare_output_file(output_file)
        log_batch_start(items, input_file)

        self.withdraw()
        run_win = SearchRunWindow(self, items, output_file)
        run_win.transient(self)
        run_win.grab_set()
        run_win.focus_force()
        run_win.lift()
        self.wait_window(run_win)
        self._cleanup_and_exit()

    def _clear_tk_vars(self) -> None:
        """Drop tk variable refs before destroy to avoid post-mainloop __del__ errors."""
        self.output_vars.clear()
        self.requirement_vars.clear()
        self.opt_vars.clear()
        self.recovery_enabled_vars.clear()

    def _cleanup_and_exit(self) -> None:
        self._clear_tk_vars()
        try:
            self.unbind_all('<MouseWheel>')
        except tk.TclError:
            pass
        self.quit()
        self.destroy()

    def destroy(self) -> None:
        self._clear_tk_vars()
        try:
            self.unbind_all('<MouseWheel>')
        except tk.TclError:
            pass
        super().destroy()


class SearchRunWindow(tk.Toplevel):
    """Live processing window with human-readable results as they arrive."""

    def __init__(self, master: tk.Misc, items: List[str], output_file: str):
        super().__init__(master)
        self.items = items
        self.output_file = output_file
        self.total = len(items)
        self.completed = 0
        self.queue: queue.Queue = queue.Queue()
        self._worker_done = False

        mode_label = 'email' if is_email_mode() else 'phone'
        self.title(f'SearchAPI — Processing {self.total} {mode_label}s')
        self.geometry('720x560')
        self.minsize(560, 420)
        self.configure(bg=BRAND['bg'])
        _apply_brand_theme(self)

        header = tk.Frame(self, bg=BRAND['header'], height=64)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        header_inner = tk.Frame(header, bg=BRAND['header'])
        header_inner.pack(fill=tk.BOTH, expand=True, padx=20, pady=14)
        tk.Label(
            header_inner, text='SearchAPI', font=FONT_TITLE,
            fg='#ffffff', bg=BRAND['header'],
        ).pack(side=tk.LEFT)
        self.status_label = tk.Label(
            header_inner, text='Starting…', font=FONT_SUB,
            fg='#94a3b8', bg=BRAND['header'],
        )
        self.status_label.pack(side=tk.RIGHT)

        body = tk.Frame(self, bg=BRAND['bg'], padx=16, pady=12)
        body.pack(fill=tk.BOTH, expand=True)

        self.progress = ttk.Progressbar(body, mode='determinate', maximum=max(self.total, 1))
        self.progress.pack(fill=tk.X, pady=(0, 8))
        self.progress_label = tk.Label(
            body, text='0 / 0', font=FONT_SMALL, fg=BRAND['muted'], bg=BRAND['bg'],
        )
        self.progress_label.pack(anchor=tk.W, pady=(0, 8))

        tk.Label(
            body, text='Live results', font=FONT_BOLD, fg=BRAND['text'], bg=BRAND['bg'],
        ).pack(anchor=tk.W, pady=(0, 4))

        output_frame = tk.Frame(
            body, bg=BRAND['card'],
            highlightbackground=BRAND['border'], highlightthickness=1,
        )
        output_frame.pack(fill=tk.BOTH, expand=True)

        self.output_text = scrolledtext.ScrolledText(
            output_frame, wrap=tk.WORD, font=FONT, bg=BRAND['card'],
            fg=BRAND['text'], relief='flat', bd=0, padx=12, pady=10,
            state=tk.DISABLED,
        )
        self.output_text.pack(fill=tk.BOTH, expand=True)
        self.output_text.tag_configure('error', foreground='#dc2626')

        footer = tk.Frame(self, bg=BRAND['bg'], pady=10, padx=16)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        self.file_label = tk.Label(
            footer, text=f'Saving to: {output_file}', font=FONT_SMALL,
            fg=BRAND['muted'], bg=BRAND['bg'],
        )
        self.file_label.pack(side=tk.LEFT)
        self.close_btn = ttk.Button(
            footer, text='Close', style='Secondary.TButton',
            command=self._on_close, state=tk.DISABLED,
        )
        self.close_btn.pack(side=tk.RIGHT)

        self.protocol('WM_DELETE_WINDOW', self._on_close)

        labels = get_mode_field_labels()
        cols = [labels.get(f, f) for f in get_output_field_order()]
        self._append_output(f"Output columns: {', '.join(cols)}\n{'─' * 48}\n")

        self.after(100, self._poll_queue)
        threading.Thread(target=self._run_batch, daemon=True).start()

    def _append_output(self, text: str, is_error: bool = False) -> None:
        self.output_text.configure(state=tk.NORMAL)
        tag = 'error' if (is_error or 'ERROR:' in text) else None
        if tag:
            self.output_text.insert(tk.END, text.rstrip() + '\n\n', tag)
        else:
            self.output_text.insert(tk.END, text.rstrip() + '\n\n')
        self.output_text.see(tk.END)
        self.output_text.configure(state=tk.DISABLED)

    def _update_progress(self, completed: int, total: int, item: str) -> None:
        self.completed = completed
        self.progress['value'] = completed
        self.progress_label.config(text=f'{completed} / {total}')
        label = 'email' if is_email_mode() else 'phone'
        self.status_label.config(text=f'Processing {label}s… ({completed}/{total})')

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, data = self.queue.get_nowait()
                if kind == 'output':
                    self._append_output(data)
                elif kind == 'progress':
                    completed, total, item = data
                    self._update_progress(completed, total, item)
                elif kind == 'done':
                    self._on_batch_done(data)
                    return
                elif kind == 'error':
                    self._append_output(f'Fatal error: {data}\n', is_error=True)
                    self._on_batch_done(None)
                    return
        except queue.Empty:
            pass
        if not self._worker_done:
            self.after(100, self._poll_queue)

    def _on_batch_done(self, message: str) -> None:
        self._worker_done = True
        label = 'email' if is_email_mode() else 'phone'
        if message:
            self.status_label.config(text=message)
        else:
            self.status_label.config(text=f'Done — {self.completed}/{self.total} {label}s processed')
        self.close_btn.configure(state=tk.NORMAL)

    def _run_batch(self) -> None:
        global LIVE_OUTPUT_CALLBACK, ON_PROGRESS_CALLBACK

        def on_output(text: str) -> None:
            self.queue.put(('output', text))

        def on_progress(completed: int, total: int, item: str) -> None:
            self.queue.put(('progress', (completed, total, item)))

        LIVE_OUTPUT_CALLBACK = on_output
        ON_PROGRESS_CALLBACK = on_progress
        try:
            run_batch(self.items, self.output_file)
            self.queue.put(('done', f'Complete — saved to {self.output_file}'))
        except Exception as e:
            self.queue.put(('error', str(e)))
        finally:
            LIVE_OUTPUT_CALLBACK = None
            ON_PROGRESS_CALLBACK = None

    def _on_close(self) -> None:
        if self._worker_done:
            self._release_and_close()
        elif messagebox.askyesno('SearchAPI', 'Processing is still running. Close anyway?'):
            self._release_and_close()

    def _release_and_close(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


def run_live_search_gui(items: List[str], output_file: str, master: tk.Misc = None) -> None:
    """Show live output window and process the batch."""
    if master is not None:
        win = SearchRunWindow(master, items, output_file)
        master.wait_window(win)
        return
    root = tk.Tk()
    root.withdraw()
    win = SearchRunWindow(root, items, output_file)
    win.protocol('WM_DELETE_WINDOW', lambda: (win._release_and_close(), root.quit()))
    root.mainloop()


def can_use_live_gui() -> bool:
    return tk is not None


def run_batch_with_live_gui(items: List[str], output_file: str) -> None:
    """Process batch in the live results window when tkinter is available."""
    if can_use_live_gui():
        run_live_search_gui(items, output_file)
    else:
        run_batch(items, output_file)


def run_config_gui(run_after_save: bool = False) -> None:
    """Show the config GUI. Save & run launches live search in the same session."""
    if tk is None:
        print('GUI unavailable: tkinter not installed')
        print('Use: python search.py --configure-cli')
        return
    try:
        app = SearchConfigApp(run_after_save=run_after_save)
        app.mainloop()
    except tk.TclError as e:
        print(f'GUI unavailable: {e}')
        print('Use: python search.py --configure-cli')

if __name__ == '__main__':
    use_gui = '--gui' in sys.argv
    use_no_gui = '--no-gui' in sys.argv or '--cli' in sys.argv
    use_configure_cli = '--configure-cli' in sys.argv
    use_configure = use_configure_cli or '-c' in sys.argv or '--configure' in sys.argv
    sys.argv = [arg for arg in sys.argv if arg not in ('--no-gui', '--cli')]
    config_loaded = load_config()
    parse_cli_mode()

    if use_gui:
        run_config_gui()
        sys.exit(0)

    if use_configure or not config_loaded:
        if use_configure_cli:
            simple_cli_setup()
        else:
            interactive_setup()
        load_config()
        parse_cli_mode()
        if use_configure and not use_gui:
            label = 'emails' if is_email_mode() else 'phones'
            print(f"Re-run to process {label}, or use --gui and click Save & run.")
            try:
                cont = input(f"Continue to process {label} now? (y/n) [y]: ").strip().lower()
                if cont in ('n', 'no'):
                    sys.exit(0)
            except EOFError:
                pass

    try:
        items, input_file, output_file = load_batch_items()
    except FileNotFoundError:
        input_file = get_input_filename()
        logger.error(
            f"Error: {input_file} not found. "
            f"Create a file with one {'email' if is_email_mode() else 'phone number'} per line."
        )
        sys.exit(1)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    prepare_output_file(output_file)
    log_batch_start(items, input_file)

    try:
        if use_no_gui:
            run_batch(items, output_file)
        else:
            run_batch_with_live_gui(items, output_file)
        logger.info(f"Processing complete. Results saved to {output_file}")
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        traceback.print_exc()
        sys.exit(1)

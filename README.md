# Search API Python Client v2.0

A comprehensive Python client library for the Search API with enhanced error handling, balance management, and improved data processing. Acquire your API key through @ADSearchEngine_bot on Telegram.

## 🚀 New in v2.0

- **Enhanced Balance Management**: Manual balance checking capabilities
- **Access Logs Integration**: Retrieve and analyze API access logs
- **Improved Error Handling**: Comprehensive exception hierarchy with detailed error messages
- **Better Data Models**: Enhanced data structures with metadata and cost tracking
- **Context Manager Support**: Automatic resource cleanup
- **Comprehensive Validation**: Input validation for all search types
- **Multiple Phone Formats**: Support for international, national, and E164 formats
- **Batch Operations**: Efficient handling of multiple searches
- **Debug Mode**: Detailed logging for troubleshooting
- **URL Encoding Fix**: Proper handling of phone numbers with + prefix
- **Response Parsing**: Robust handling of both list and dictionary API responses

## 📦 Installation

```bash
pip install AD-SearchAPI
```

## ⚡ Quick Start

```python
from search_api import SearchAPI, InsufficientBalanceError

client = SearchAPI(api_key="your_api_key")

try:
    balance = client.get_balance()
    print(f"Current balance: {balance}")
    print(f"Cost per search: ${balance.credit_cost_per_search}")
    
    access_logs = client.get_access_logs()
    print(f"Total access log entries: {len(access_logs)}")
    
    result = client.search_email(
        "example@domain.com",
        house_value=True,
        extra_info=True
    )
    
    print(f"Name: {result.person.name if result.person else 'N/A'}")
    print(f"Total results: {result.total_results}")
    print(f"Search cost: ${result.search_cost}")
    
    for addr in result.addresses:
        print(f"Address: {addr}")
        if addr.zestimate:
            print(f"  Zestimate: ${addr.zestimate:,.2f}")
    
except InsufficientBalanceError as e:
    print(f"Insufficient balance: {e}")
    print(f"Current: {e.current_balance}, Required: {e.required_credits}")
```

## 🔧 Advanced Configuration

```python
from search_api import SearchAPI, SearchAPIConfig

config = SearchAPIConfig(
    api_key="your_api_key",
    debug_mode=True,           # Enable debug logging
    timeout=120,              # 2 minutes timeout
    max_retries=5,           # Retry failed requests
    proxy={                   # Optional proxy
        "http": "http://proxy:8080",
        "https": "https://proxy:8080"
    }
)

client = SearchAPI(config=config)
```

## 💰 Balance Management

The client provides balance checking capabilities, but does not automatically check balance before each search. You should check your balance manually when needed:

```python
from search_api import InsufficientBalanceError

try:
    balance = client.get_balance()
    print(f"Balance: {balance.current_balance} {balance.currency}")
    print(f"Cost per search: {balance.credit_cost_per_search}")
    
    # Calculate required credits based on actual search costs
    email_search_cost = 0.0025
    phone_search_cost = 0.0025
    domain_search_cost = 0.0025
    
    required_credits = 5 * email_search_cost
    if balance.current_balance < required_credits:
        print(f"⚠️  Insufficient balance for {required_credits} searches")
    else:
        print(f"✅ Sufficient balance for {required_credits} searches")
        
except InsufficientBalanceError as e:
    print(f"❌ Insufficient balance: {e}")
    print(f"   Current: {e.current_balance}")
    print(f"   Required: {e.required_credits}")
```

## 💵 Pricing Information

### Search Costs:
- **Email Search**: $0.0025 per search
- **Phone Search**: $0.0025 per search  
- **Domain Search**: $0.0025 per search

### Optional Parameters:
- **House Value (Zestimate)**: Additional $0.0015 per successful lookup
- **Extra Info**: Additional $0.0015 per successful lookup
- **Carrier Info**: Additional $0.0005 per successful lookup
- **TLO Enrichment**: Additional $0.0030 per successful lookup

## 📊 Access Logs

Retrieve and analyze your API access logs:

```python
# Get all access logs
access_logs = client.get_access_logs()

print(f"Total access log entries: {len(access_logs)}")

# Show recent activity
for log in access_logs[:5]:
    print(f"IP: {log.ip_address}")
    print(f"Last accessed: {log.last_accessed}")
    print(f"Endpoint: {log.endpoint}")
    print(f"Status: {log.status_code}")
    print(f"Response time: {log.response_time:.3f}s")
    print("---")

# Analyze access patterns
unique_ips = set(log.ip_address for log in access_logs)
print(f"Unique IP addresses: {len(unique_ips)}")

# Find most active IP
ip_counts = {}
for log in access_logs:
    ip_counts[log.ip_address] = ip_counts.get(log.ip_address, 0) + 1

most_active_ip = max(ip_counts.items(), key=lambda x: x[1])
print(f"Most active IP: {most_active_ip[0]} ({most_active_ip[1]} accesses)")
```

## 🔍 Search Operations

### Email Search

```python
result = client.search_email(
    "john.doe@example.com",
    house_value=True,
    extra_info=True,
    carrier_info=True,
    tlo_enrichment=True,
    phone_format="international"  # or "national", "e164"
)

print(f"Email: {result.email}")
print(f"Valid: {result.email_valid}")
print(f"Type: {result.email_type}")
print(f"Search Cost: ${result.search_cost}")

# Access detailed pricing breakdown
if result.pricing:
    print(f"Pricing Breakdown:")
    print(f"  Base Search: ${result.pricing.search_cost:.4f}")
    print(f"  Extra Info: ${result.pricing.extra_info_cost:.4f}")
    print(f"  Zestimate: ${result.pricing.zestimate_cost:.4f}")
    print(f"  Carrier: ${result.pricing.carrier_cost:.4f}")
    print(f"  TLO Enrichment: ${result.pricing.tlo_enrichment_cost:.4f}")
    print(f"  Total Cost: ${result.pricing.total_cost:.4f}")

if result.person:
    print(f"Name: {result.person.name}")
    print(f"DOB: {result.person.dob}")
    print(f"Age: {result.person.age}")

for addr in result.addresses:
    print(f"Address: {addr}")
    if addr.zestimate:
        print(f"  Zestimate: ${addr.zestimate:,.2f}")

for phone in result.phone_numbers:
    print(f"Phone: {phone.number}")
```

### Phone Search

```python
results = client.search_phone(
    "+1234567890",
    house_value=True,
    extra_info=True,
    carrier_info=True,
    tlo_enrichment=True,
    phone_format="international"
)

for result in results:
    print(f"Phone: {result.phone.number}")
    print(f"Search Cost: ${result.search_cost}")
    
    # Access detailed pricing breakdown
    if result.pricing:
        print(f"  Total Cost: ${result.pricing.total_cost:.4f}")
        print(f"  Breakdown: {result.pricing}")
    
    if result.person:
        print(f"Name: {result.person.name}")
        print(f"DOB: {result.person.dob}")
    
    print(f"Total results: {result.total_results}")
```

### Domain Search

```python
result = client.search_domain("example.com")

print(f"Domain: {result.domain}")
print(f"Valid: {result.domain_valid}")
print(f"Total results: {result.total_results}")
print(f"Search Cost: ${result.search_cost}")

# Access detailed pricing breakdown
if result.pricing:
    print(f"Pricing: {result.pricing}")

for email_result in result.results:
    print(f"Email: {email_result.email}")
    print(f"Valid: {email_result.email_valid}")
    print(f"Type: {email_result.email_type}")
    
    if email_result.person:
        print(f"Name: {email_result.person.name}")
```

## 🛡️ Error Handling

The library provides comprehensive error handling with specific exception types:

```python
from search_api import (
    SearchAPIError,
    AuthenticationError,
    ValidationError,
    InsufficientBalanceError,
    RateLimitError,
    ServerError,
    NetworkError,
    TimeoutError,
    ConfigurationError
)

try:
    result = client.search_email("test@example.com")
except ValidationError as e:
    print(f"Invalid input: {e}")
except InsufficientBalanceError as e:
    print(f"Insufficient balance: {e}")
    print(f"Current: {e.current_balance}, Required: {e.required_credits}")
except AuthenticationError as e:
    print(f"Authentication failed: {e}")
except RateLimitError as e:
    print(f"Rate limit exceeded: {e}")
except ServerError as e:
    print(f"Server error: {e}")
except NetworkError as e:
    print(f"Network error: {e}")
except TimeoutError as e:
    print(f"Request timeout: {e}")
except SearchAPIError as e:
    print(f"API error: {e}")
```

## 🧹 Context Manager

Use the client as a context manager for automatic resource cleanup:

```python
with SearchAPI(api_key="your_api_key") as client:
    balance = client.get_balance()
    result = client.search_email("test@example.com")
    # Resources automatically cleaned up when exiting context
```

## 📊 Data Models

### Address Model

```python
@dataclass
class Address:
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
```

### Person Model

```python
@dataclass
class Person:
    name: Optional[str] = None
    dob: Optional[date] = None
    age: Optional[int] = None
```

### PhoneNumber Model

```python
@dataclass
class PhoneNumber:
    number: str
    country_code: str = "US"
    is_valid: bool = True
    phone_type: Optional[str] = None
    carrier: Optional[str] = None
```

### BalanceInfo Model

```python
@dataclass
class BalanceInfo:
    current_balance: float
    currency: str = "USD"
    last_updated: Optional[datetime] = None
    credit_cost_per_search: Optional[float] = None
```

### AccessLog Model

```python
@dataclass
class AccessLog:
    ip_address: str
    last_accessed: Optional[datetime] = None
    user_agent: Optional[str] = None
    endpoint: Optional[str] = None
    method: Optional[str] = None
    status_code: Optional[int] = None
    response_time: Optional[float] = None
```

## 🔧 Configuration Options

### SearchAPIConfig

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `api_key` | str | Required | Your API key |
| `base_url` | str | `"https://search-api.dev/search.php"` | API base URL |
| `max_retries` | int | `1` | Maximum retry attempts |
| `timeout` | int | `90` | Request timeout in seconds |
| `debug_mode` | bool | `False` | Enable debug logging |
| `proxy` | Dict | `None` | Proxy configuration |
| `user_agent` | str | Chrome UA | Custom user agent |

## 📝 Examples

See the `examples/` directory for comprehensive usage examples:

- `basic_usage.py` - Basic search operations, balance checking, and access logs
- `advanced_usage.py` - Advanced features like caching, batch operations, and access log analysis

## 🤝 Contributing

Contributions are welcome! Please submit a Pull Request with your changes or open an issue for discussion.

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

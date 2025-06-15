# Search API Python Client

A Python client library for the Search API, providing easy access to email, phone, and domain search functionality.

## Installation

```bash
pip install search-api
```

## Quick Start

```python
from search_api import SearchAPI

# Initialize the client with your API key
client = SearchAPI(api_key="your_api_key")

# Search by email
result = client.search_email("example@domain.com", include_house_value=True)
print(result)

# Search by phone
result = client.search_phone("+1234567890", include_extra_info=True)
print(result)

# Search by domain
result = client.search_domain("example.com")
print(result)
```

## Features

- Email search with optional house value and extra info
- Phone number search with validation and formatting
- Domain search with comprehensive results
- Automatic caching of results
- Rate limiting and retry handling
- Type hints and comprehensive documentation

## Advanced Usage

### Configuration

```python
from search_api import SearchAPI, SearchAPIConfig

config = SearchAPIConfig(
    api_key="your_api_key",
    cache_ttl=3600,  # Cache results for 1 hour
    max_retries=3,
    timeout=30,
    base_url="https://search-api.dev"
)

client = SearchAPI(config=config)
```

### Error Handling

```python
from search_api import SearchAPIError

try:
    result = client.search_email("example@domain.com")
except SearchAPIError as e:
    print(f"Error: {e.message}")
    print(f"Status code: {e.status_code}")
```

## API Reference

### SearchAPI

Main client class for interacting with the Search API.

#### Methods

- `search_email(email: str, include_house_value: bool = False, include_extra_info: bool = False) -> Dict`
- `search_phone(phone: str, include_house_value: bool = False, include_extra_info: bool = False) -> Dict`
- `search_domain(domain: str) -> Dict`

### SearchAPIConfig

Configuration class for customizing client behavior.

#### Parameters

- `api_key: str` - Your API key
- `cache_ttl: int` - Cache time-to-live in seconds
- `max_retries: int` - Maximum number of retry attempts
- `timeout: int` - Request timeout in seconds
- `base_url: str` - API base URL

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details. 
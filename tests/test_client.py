import pytest
from unittest.mock import Mock, patch
from datetime import date
from decimal import Decimal

from search_api import SearchAPI, SearchAPIConfig
from search_api.exceptions import (
    AuthenticationError,
    ValidationError,
    SearchAPIError,
)
from search_api.models import Address, PhoneNumber


@pytest.fixture
def client():
    return SearchAPI(api_key="test_api_key")


@pytest.fixture
def mock_response():
    return {
        "name": "John Doe",
        "dob": "1990-01-01",
        "addresses": [
            "123 Main St, New York, NY 10001",
            {
                "street": "456 Park Ave",
                "city": "New York",
                "state": "NY",
                "postal_code": "10022",
                "zestimate": 1500000,
            },
        ],
        "numbers": ["+12125551234", "+12125556789"],
    }


def test_init_with_api_key():
    client = SearchAPI(api_key="test_api_key")
    assert client.config.api_key == "test_api_key"
    assert client.config.base_url == "https://search-api.dev"


def test_init_with_config():
    config = SearchAPIConfig(
        api_key="test_api_key",
        max_retries=5,
        timeout=60,
        base_url="https://custom-api.dev",
    )
    client = SearchAPI(config=config)
    assert client.config == config


def test_init_without_api_key_or_config():
    with pytest.raises(ValueError):
        SearchAPI()


@patch("requests.Session.request")
def test_search_email_success(mock_request, client, mock_response):
    mock_request.return_value.json.return_value = mock_response
    mock_request.return_value.status_code = 200

    result = client.search_email("test@example.com")

    assert result.name == "John Doe"
    assert result.dob == date(1990, 1, 1)
    assert len(result.addresses) == 2
    assert len(result.phone_numbers) == 2
    assert isinstance(result.addresses[0], Address)
    assert isinstance(result.phone_numbers[0], PhoneNumber)
    assert result.addresses[1].zestimate == Decimal("1500000")


@patch("requests.Session.request")
def test_search_email_invalid_format(client):
    with pytest.raises(ValidationError):
        client.search_email("invalid-email")


@patch("requests.Session.request")
def test_search_email_api_error(client):
    mock_response = Mock()
    mock_response.status_code = 401
    mock_response.text = "Invalid API key"
    mock_response.json.return_value = {"error": "Invalid API key"}

    with patch("requests.Session.request", return_value=mock_response):
        with pytest.raises(AuthenticationError):
            client.search_email("test@example.com")


@patch("requests.Session.request")
def test_search_phone_success(mock_request, client, mock_response):
    mock_request.return_value.json.return_value = mock_response
    mock_request.return_value.status_code = 200

    result = client.search_phone("+12125551234")

    assert result.name == "John Doe"
    assert result.dob == date(1990, 1, 1)
    assert len(result.addresses) == 2
    assert len(result.phone_numbers) == 2
    assert isinstance(result.addresses[0], Address)
    assert isinstance(result.phone_numbers[0], PhoneNumber)
    assert result.addresses[1].zestimate == Decimal("1500000")


@patch("requests.Session.request")
def test_search_phone_invalid_format(client):
    with pytest.raises(ValidationError):
        client.search_phone("invalid-phone")


@patch("requests.Session.request")
def test_search_domain_success(mock_request, client):
    mock_response = {
        "results": [
            {
                "email": "test1@example.com",
                "name": "John Doe",
                "addresses": ["123 Main St, New York, NY 10001"],
                "phone_numbers": ["+12125551234"],
            },
            {
                "email": "test2@example.com",
                "name": "Jane Smith",
                "addresses": ["456 Park Ave, New York, NY 10022"],
                "phone_numbers": ["+12125556789"],
            },
        ]
    }
    mock_request.return_value.json.return_value = mock_response
    mock_request.return_value.status_code = 200

    result = client.search_domain("example.com")

    assert result.domain == "example.com"
    assert result.total_results == 2
    assert len(result.results) == 2
    assert result.results[0].email == "test1@example.com"
    assert result.results[1].email == "test2@example.com"


@patch("requests.Session.request")
def test_search_domain_major_domain(client):
    with pytest.raises(ValidationError):
        client.search_domain("gmail.com")


@patch("requests.Session.request")
def test_search_domain_invalid_format(client):
    with pytest.raises(ValidationError):
        client.search_domain("invalid-domain")


def test_format_address(client):
    address = "123 main st, new york, ny 10001"
    formatted = client._format_address(address)
    assert formatted == "123 Main Street, New York, NY 10001"


def test_parse_phone_number(client):
    phone = "+12125551234"
    result = client._parse_phone_number(phone)
    assert isinstance(result, PhoneNumber)
    assert result.number == "+12125551234"
    assert result.is_valid is True


def test_parse_phone_number_invalid(client):
    phone = "invalid-phone"
    result = client._parse_phone_number(phone)
    assert isinstance(result, PhoneNumber)
    assert result.number == "invalid-phone"
    assert result.is_valid is False


@patch("requests.Session.request")
def test_compression_handling(mock_request, client):
    """Test that the client properly handles gzipped/compressed responses."""
    # Mock response with gzip encoding
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.headers = {
        'Content-Encoding': 'gzip',
        'Content-Length': '1234'
    }
    mock_response.text = '{"name": "John Doe", "email": "test@example.com"}'
    mock_response.json.return_value = {"name": "John Doe", "email": "test@example.com"}
    mock_response.raise_for_status.return_value = None
    
    mock_request.return_value = mock_response
    
    # Test that the request is made with proper headers
    result = client.search_email("test@example.com")
    
    # Verify that Accept-Encoding header is set in the session
    assert "Accept-Encoding" in client.session.headers
    assert "gzip" in client.session.headers["Accept-Encoding"]
    
    # Verify that the request was made
    mock_request.assert_called_once()
    
    # Verify that the response was properly handled
    assert result.name == "John Doe"
    assert result.email == "test@example.com"


@patch("requests.Session.request")
def test_gzip_decompression(mock_request, client):
    """Test that gzipped responses are properly decompressed."""
    import gzip
    import json
    
    # Create a gzipped JSON response
    original_data = {"name": "Jane Smith", "email": "jane@example.com"}
    json_str = json.dumps(original_data)
    gzipped_content = gzip.compress(json_str.encode('utf-8'))
    
    # Mock response with gzipped content
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.headers = {
        'Content-Encoding': 'gzip',
        'Content-Length': str(len(gzipped_content))
    }
    mock_response.content = gzipped_content
    mock_response.text = json_str  # This should be the decompressed text
    mock_response.raise_for_status.return_value = None
    
    mock_request.return_value = mock_response
    
    # Test that gzipped response is properly handled
    result = client.search_email("jane@example.com")
    
    # Verify that the response was properly decompressed and parsed
    assert result.name == "Jane Smith"
    assert result.email == "jane@example.com"


@patch("requests.Session.request")
def test_compression_debug_logging(mock_request, client):
    """Test that compression information is logged in debug mode."""
    # Create client with debug mode enabled
    debug_config = SearchAPIConfig(api_key="test_api_key", debug_mode=True)
    debug_client = SearchAPI(config=debug_config)
    
    # Mock response with compression headers
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.headers = {
        'Content-Encoding': 'gzip',
        'Content-Length': '567'
    }
    mock_response.text = '{"name": "Jane Smith"}'
    mock_response.json.return_value = {"name": "Jane Smith"}
    mock_response.raise_for_status.return_value = None
    mock_response.encoding = 'utf-8'
    
    mock_request.return_value = mock_response
    
    # Test that debug logging includes compression info
    with patch('logging.Logger.debug') as mock_debug:
        debug_client.search_email("test@example.com")
        
        # Verify that compression headers were logged
        debug_calls = [call[0][0] for call in mock_debug.call_args_list]
        compression_logged = any('Content-Encoding' in str(call) for call in debug_calls)
        assert compression_logged, "Compression headers should be logged in debug mode"


@patch("requests.Session.request")
def test_gzip_magic_bytes_detection(mock_request, client):
    """Test that gzipped responses are detected by magic bytes even without Content-Encoding header."""
    import gzip
    import json
    
    # Create a gzipped JSON response
    original_data = {"name": "Bob Johnson", "email": "bob@example.com"}
    json_str = json.dumps(original_data)
    gzipped_content = gzip.compress(json_str.encode('utf-8'))
    
    # Mock response with gzipped content but no Content-Encoding header
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.headers = {
        'Content-Length': str(len(gzipped_content))
        # No Content-Encoding header
    }
    mock_response.content = gzipped_content
    mock_response.text = json_str
    mock_response.raise_for_status.return_value = None
    
    mock_request.return_value = mock_response
    
    # Test that gzipped response is detected by magic bytes and properly handled
    result = client.search_email("bob@example.com")
    
    # Verify that the response was properly decompressed and parsed
    assert result.name == "Bob Johnson"
    assert result.email == "bob@example.com"


@patch("requests.Session.request")
def test_brotli_decompression(mock_request, client):
    """Test that Brotli-compressed responses are properly decompressed."""
    try:
        import brotli
    except ImportError:
        pytest.skip("brotli library not available")
    
    import json
    
    # Create a Brotli-compressed JSON response
    original_data = {"name": "Alice Brown", "email": "alice@example.com"}
    json_str = json.dumps(original_data)
    brotli_content = brotli.compress(json_str.encode('utf-8'))
    
    # Mock response with Brotli-compressed content
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.headers = {
        'Content-Encoding': 'br',
        'Content-Length': str(len(brotli_content))
    }
    mock_response.content = brotli_content
    mock_response.text = json_str
    mock_response.raise_for_status.return_value = None
    
    mock_request.return_value = mock_response
    
    # Test that Brotli-compressed response is properly handled
    result = client.search_email("alice@example.com")
    
    # Verify that the response was properly decompressed and parsed
    assert result.name == "Alice Brown"
    assert result.email == "alice@example.com" 
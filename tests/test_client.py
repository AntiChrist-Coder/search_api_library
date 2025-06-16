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
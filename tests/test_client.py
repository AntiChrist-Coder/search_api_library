import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, date
from decimal import Decimal

from search_api import (
    SearchAPI,
    SearchAPIConfig,
    SearchAPIError,
    AuthenticationError,
    ValidationError,
    RateLimitError,
    InsufficientBalanceError,
    ServerError,
    NetworkError,
    TimeoutError,
    ConfigurationError,
    Address,
    PhoneNumber,
    Person,
    EmailSearchResult,
    PhoneSearchResult,
    DomainSearchResult,
    BalanceInfo,
    AccessLog,
    PhoneFormat,
    SearchType,
)


class TestSearchAPIConfig:
    """Test SearchAPIConfig validation."""
    
    def test_valid_config(self):
        """Test valid configuration."""
        config = SearchAPIConfig(api_key="test_key")
        assert config.api_key == "test_key"
        assert config.max_retries == 1  # Default is 1, not 3
        assert config.timeout == 90
    
    def test_invalid_api_key(self):
        """Test that empty API key raises error."""
        with pytest.raises(ValueError, match="API key is required"):
            SearchAPIConfig(api_key="")
    
    def test_invalid_timeout(self):
        """Test that negative timeout raises error."""
        with pytest.raises(ValueError, match="Timeout must be positive"):
            SearchAPIConfig(api_key="test_key", timeout=0)
    
    def test_invalid_retries(self):
        """Test that negative retries raises error."""
        with pytest.raises(ValueError, match="Max retries must be non-negative"):
            SearchAPIConfig(api_key="test_key", max_retries=-1)


class TestSearchAPI:
    """Test SearchAPI functionality."""
    
    @pytest.fixture
    def client(self):
        """Create a test client."""
        config = SearchAPIConfig(api_key="test_key", debug_mode=False)
        return SearchAPI(config=config)
    
    def test_init_with_api_key(self):
        """Test initialization with API key."""
        client = SearchAPI(api_key="test_key")
        assert client.config.api_key == "test_key"
    
    def test_init_with_config(self):
        """Test initialization with config."""
        config = SearchAPIConfig(api_key="test_key")
        client = SearchAPI(config=config)
        assert client.config.api_key == "test_key"
    
    def test_init_without_key_or_config(self):
        """Test that initialization without key or config raises error."""
        with pytest.raises(ConfigurationError):
            SearchAPI()
    
    def test_validate_email(self, client):
        """Test email validation."""
        assert client._validate_email("test@example.com") is True
        assert client._validate_email("invalid-email") is False
        assert client._validate_email("") is False
        assert client._validate_email(None) is False
    
    def test_validate_phone(self, client):
        """Test phone validation."""
        assert client._validate_phone("+1234567890") is True
        assert client._validate_phone("invalid-phone") is False
        assert client._validate_phone("") is False
        assert client._validate_phone(None) is False
    
    def test_validate_domain(self, client):
        """Test domain validation."""
        assert client._validate_domain("example.com") is True
        assert client._validate_domain("invalid-domain") is False
        assert client._validate_domain("") is False
        assert client._validate_domain(None) is False
    
    @patch.object(SearchAPI, '_parse_response')
    def test_get_balance_success(self, mock_parse_response, client):
        """Test successful balance retrieval."""
        mock_parse_response.return_value = {"balance": "12461.1595"}
        
        with patch.object(client.session, 'get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            balance = client.get_balance()
            
            assert isinstance(balance, BalanceInfo)
            assert balance.current_balance == 12461.1595
            assert balance.currency == "USD"
            assert balance.credit_cost_per_search == 0.0025
            assert balance.last_updated is not None
    
    @patch.object(SearchAPI, '_parse_response')
    def test_get_balance_invalid_response(self, mock_parse_response, client):
        """Test balance retrieval with invalid response."""
        mock_parse_response.return_value = {"invalid": "response"}
        
        with patch.object(client.session, 'get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            with pytest.raises(ServerError, match="Invalid balance response"):
                client.get_balance()
    
    @patch.object(SearchAPI, '_parse_response')
    def test_get_access_logs_success(self, mock_parse_response, client):
        """Test successful access logs retrieval."""
        mock_parse_response.return_value = {
            "logs": [
                {
                    "ip_address": "54.221.146.102",
                    "last_accessed": "2025-08-03 21:24:57"
                },
                {
                    "ip_address": "54.158.89.194",
                    "last_accessed": "2025-08-03 21:24:57"
                }
            ]
        }
        
        with patch.object(client.session, 'get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            access_logs = client.get_access_logs()
            
            assert isinstance(access_logs, list)
            assert len(access_logs) == 2
            assert all(isinstance(log, AccessLog) for log in access_logs)
            assert access_logs[0].ip_address == "54.221.146.102"
            assert access_logs[1].ip_address == "54.158.89.194"
    
    @patch.object(SearchAPI, '_parse_response')
    def test_get_access_logs_invalid_response(self, mock_parse_response, client):
        """Test access logs retrieval with invalid response."""
        mock_parse_response.return_value = {"invalid": "response"}
        
        with patch.object(client.session, 'get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            with pytest.raises(ServerError, match="Invalid access logs response"):
                client.get_access_logs()
    
    @patch.object(SearchAPI, 'get_balance')
    def test_check_balance_sufficient(self, mock_get_balance, client):
        """Test balance check with sufficient balance."""
        mock_get_balance.return_value = BalanceInfo(current_balance=10.0)
        
        # Should not raise exception
        client._check_balance(required_credits=5)
    
    @patch.object(SearchAPI, 'get_balance')
    def test_check_balance_insufficient(self, mock_get_balance, client):
        """Test balance check with insufficient balance."""
        # Mock insufficient balance
        mock_balance = BalanceInfo(current_balance=0.5)
        mock_get_balance.return_value = mock_balance

        with pytest.raises(InsufficientBalanceError) as exc_info:
            client._check_balance(required_credits=1)
        
        assert exc_info.value.current_balance == 0.5
        assert exc_info.value.required_credits == 1
    
    def test_search_email_invalid_input(self, client):
        """Test email search with invalid input."""
        with pytest.raises(ValidationError, match="Invalid email format"):
            client.search_email("invalid-email")
    
    @patch.object(SearchAPI, '_check_balance')
    @patch.object(SearchAPI, '_make_request')
    def test_search_email_success(self, mock_request, mock_check_balance, client):
        """Test successful email search."""
        mock_request.return_value = {
            "email": "test@example.com",
            "name": "John Doe",
            "dob": "1990-01-01",
            "age": 33,
            "addresses": [
                "123 Main St, City, ST 12345",
                {
                    "address": "456 Oak Ave, Town, ST 67890",
                    "zestimate": 250000,
                    "zpid": "12345",
                    "property_details": {
                        "street_address": "456 Oak Ave",
                        "city": "Town",
                        "state": "ST",
                        "zipcode": "67890",
                        "bedrooms": 3,
                        "bathrooms": 2.5,
                        "living_area": 1500,
                        "home_status": "RECENTLY_SOLD"
                    }
                }
            ],
            "numbers": ["+1234567890", "+1987654321"],
            "emails": ["john@example.com"],
            "email_valid": True,
            "email_type": "personal"
        }

        result = client.search_email("test@example.com")

        assert isinstance(result, EmailSearchResult)
        assert result.email == "test@example.com"
        assert result.email_valid is True
        assert result.email_type == "personal"
        assert result.search_cost == 0.0025
        assert len(result.addresses) == 2
        assert len(result.phone_numbers) == 2
        assert len(result.emails) == 1

    def test_search_phone_invalid_input(self, client):
        """Test phone search with invalid input."""
        with pytest.raises(ValidationError, match="Invalid phone number format"):
            client.search_phone("invalid-phone")
    
    @patch.object(SearchAPI, '_check_balance')
    @patch.object(SearchAPI, '_make_request')
    def test_search_phone_success(self, mock_request, mock_check_balance, client):
        """Test successful phone search."""
        mock_request.return_value = {
            "name": "Jane Smith",
            "dob": "1985-05-15",
            "age": 38,
            "addresses": ["456 Oak Ave, Town, ST 67890"],
            "numbers": ["+1987654321"],
            "emails": ["jane@example.com"]
        }

        results = client.search_phone("+1234567890")

        assert isinstance(results, list)
        assert len(results) == 1
        result = results[0]
        assert isinstance(result, PhoneSearchResult)
        assert result.phone.number == "+1234567890"
        assert result.search_cost == 0.0025
        assert len(result.addresses) == 1
        assert len(result.phone_numbers) == 1
        assert len(result.emails) == 1

    def test_search_domain_invalid_input(self, client):
        """Test domain search with invalid input."""
        with pytest.raises(ValidationError, match="Invalid domain format"):
            client.search_domain("invalid-domain")
    
    @patch.object(SearchAPI, '_check_balance')
    @patch.object(SearchAPI, '_make_request')
    def test_search_domain_success(self, mock_request, mock_check_balance, client):
        """Test successful domain search."""
        mock_request.return_value = {
            "results": [
                {
                    "email": "user1@example.com",
                    "name": "User One",
                    "addresses": ["123 Main St"],
                    "numbers": ["+1234567890"],
                    "emails": ["user1@example.com"],
                    "email_valid": True,
                    "email_type": "business"
                }
            ],
            "domain_valid": True
        }

        result = client.search_domain("example.com")

        assert isinstance(result, DomainSearchResult)
        assert result.domain == "example.com"
        assert result.domain_valid is True
        assert result.search_cost == 4.00
        assert len(result.results) == 1
        assert result.results[0].email == "user1@example.com"
    
    def test_close(self, client):
        """Test client cleanup."""
        client.session = Mock()
        
        client.close()
        
        client.session.close.assert_called_once()
    
    def test_context_manager(self, client):
        """Test context manager functionality."""
        client.close = Mock()
        
        with client:
            pass
        
        client.close.assert_called_once()


class TestExceptions:
    """Test exception classes."""
    
    def test_search_api_error(self):
        """Test base SearchAPIError."""
        error = SearchAPIError("Test error", status_code=400)
        assert str(error) == "Error: Test error (Status: 400)"
        assert error.status_code == 400
    
    def test_insufficient_balance_error(self):
        """Test InsufficientBalanceError."""
        error = InsufficientBalanceError(
            current_balance=5.0,
            required_credits=10,
            status_code=402
        )
        assert "Insufficient balance" in str(error)
        assert error.current_balance == 5.0
        assert error.required_credits == 10
    
    def test_validation_error(self):
        """Test ValidationError."""
        error = ValidationError("Invalid input")
        assert str(error) == "Error: Invalid input"
    
    def test_authentication_error(self):
        """Test AuthenticationError."""
        error = AuthenticationError("Invalid API key", status_code=401)
        assert str(error) == "Error: Invalid API key (Status: 401)"


class TestModels:
    """Test data models."""
    
    def test_address_model(self):
        """Test Address model."""
        address = Address(
            street="123 Main St",
            city="City",
            state="ST",
            postal_code="12345",
            zestimate=Decimal("250000.00"),
            bedrooms=3,
            bathrooms=2.5
        )
        
        assert address.street == "123 Main St"
        assert address.zestimate == Decimal("250000.00")
        assert "123 Main St" in str(address)
    
    def test_phone_number_model(self):
        """Test PhoneNumber model."""
        phone = PhoneNumber(
            number="+1 234-567-890",
            is_valid=True,
            phone_type="MOBILE",
            carrier="Verizon"
        )
        
        assert phone.number == "+1 234-567-890"
        assert phone.is_valid is True
        assert phone.phone_type == "MOBILE"
        assert phone.carrier == "Verizon"
    
    def test_person_model(self):
        """Test Person model."""
        person = Person(
            name="John Doe",
            dob=date(1990, 1, 1),
            age=33
        )
        
        assert person.name == "John Doe"
        assert person.dob == date(1990, 1, 1)
        assert person.age == 33
        assert str(person) == "John Doe"
    
    def test_balance_info_model(self):
        """Test BalanceInfo model."""
        balance = BalanceInfo(
            current_balance=100.0,
            currency="USD",
            last_updated=datetime.now(),
            credit_cost_per_search=0.0025
        )
        
        assert balance.current_balance == 100.0
        assert balance.currency == "USD"
        assert balance.credit_cost_per_search == 0.0025
        assert balance.last_updated is not None
        assert "100.0 USD" in str(balance)
    
    def test_access_log_model(self):
        """Test AccessLog model."""
        access_log = AccessLog(
            ip_address="192.168.1.1",
            last_accessed=datetime(2025, 8, 3, 21, 24, 57),
            endpoint="/api/search",
            method="POST",
            status_code=200,
            response_time=0.5
        )
        
        assert access_log.ip_address == "192.168.1.1"
        assert access_log.last_accessed == datetime(2025, 8, 3, 21, 24, 57)
        assert access_log.endpoint == "/api/search"
        assert access_log.method == "POST"
        assert access_log.status_code == 200
        assert access_log.response_time == 0.5
        assert "192.168.1.1" in str(access_log) 
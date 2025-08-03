import logging
from datetime import datetime
from search_api import (
    SearchAPI, 
    SearchAPIConfig, 
    InsufficientBalanceError, 
    ValidationError,
    RateLimitError,
    AuthenticationError,
    ServerError,
    NetworkError,
    TimeoutError,
    PhoneFormat,
    SearchType,
)

def setup_logging():
    """Setup logging for debugging."""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

def demonstrate_balance_management(client):
    """Demonstrate balance checking and management."""
    print("\n" + "="*60)
    print("BALANCE MANAGEMENT")
    print("="*60)
    
    try:
        # Get current balance
        balance = client.get_balance()
        print(f"Current Balance: {balance}")
        print(f"Currency: {balance.currency}")
        print(f"Cost per search: ${balance.credit_cost_per_search}")
        print(f"Last updated: {balance.last_updated}")
        
        # Check if we have enough balance for multiple searches
        # Calculate cost for 5 email searches (most common)
        email_search_cost = 0.0025
        required_credits = 5 * email_search_cost  # 5 email searches
        if balance.current_balance < required_credits:
            print(f"⚠️  Warning: Insufficient balance for 5 email searches")
            print(f"   Current: ${balance.current_balance:.4f}, Required: ${required_credits:.4f}")
        else:
            print(f"✅ Sufficient balance for 5 email searches")
            
        # Check for domain search (much more expensive)
        domain_search_cost = 4.00
        if balance.current_balance < domain_search_cost:
            print(f"⚠️  Warning: Insufficient balance for 1 domain search")
            print(f"   Current: ${balance.current_balance:.4f}, Required: ${domain_search_cost:.2f}")
        else:
            print(f"✅ Sufficient balance for 1 domain search")
            
    except Exception as e:
        print(f"❌ Error checking balance: {e}")

def demonstrate_access_logs(client):
    """Demonstrate access logs functionality."""
    print("\n" + "="*60)
    print("ACCESS LOGS")
    print("="*60)
    
    try:
        # Get access logs
        access_logs = client.get_access_logs()
        print(f"📊 Total access log entries: {len(access_logs)}")
        
        if access_logs:
            # Show most recent access
            most_recent = max(access_logs, key=lambda x: x.last_accessed or datetime.min)
            print(f"🕒 Most recent access: {most_recent.last_accessed}")
            print(f"🌐 IP Address: {most_recent.ip_address}")
            
            # Show unique IP addresses
            unique_ips = set(log.ip_address for log in access_logs)
            print(f"🌍 Unique IP addresses: {len(unique_ips)}")
            
            # Show access frequency by IP
            ip_counts = {}
            for log in access_logs:
                ip_counts[log.ip_address] = ip_counts.get(log.ip_address, 0) + 1
            
            print("\n📈 Access frequency by IP:")
            for ip, count in sorted(ip_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
                print(f"   {ip}: {count} accesses")
            
            # Show recent activity (last 10 entries)
            print(f"\n📋 Recent activity (last 10 entries):")
            for i, log in enumerate(access_logs[:10], 1):
                print(f"   {i}. {log.ip_address} - {log.last_accessed}")
                if log.endpoint:
                    print(f"      Endpoint: {log.endpoint}")
                if log.status_code:
                    print(f"      Status: {log.status_code}")
                if log.response_time:
                    print(f"      Response Time: {log.response_time:.3f}s")
        else:
            print("📭 No access logs found")
            
    except Exception as e:
        print(f"❌ Error retrieving access logs: {e}")

def demonstrate_caching(client):
    """Demonstrate caching functionality."""
    print("\n" + "="*60)
    print("CACHING DEMONSTRATION")
    print("="*60)
    
    email = "michael.campbell@gmail.com"
    
    # First search (will be cached)
    print(f"🔍 First search for {email}...")
    start_time = datetime.now()
    result1 = client.search_email(email)
    time1 = (datetime.now() - start_time).total_seconds()
    print(f"   Time taken: {time1:.3f}s")
    print(f"   Results: {result1.total_results}")
    
    # Second search (should be from cache)
    print(f"🔍 Second search for {email} (should be cached)...")
    start_time = datetime.now()
    result2 = client.search_email(email)
    time2 = (datetime.now() - start_time).total_seconds()
    print(f"   Time taken: {time2:.3f}s")
    print(f"   Results: {result2.total_results}")
    
    if time2 < time1:
        print("✅ Cache is working (second request was faster)")
    else:
        print("⚠️  Cache might not be working as expected")
    
    # Clear cache
    print("🧹 Clearing cache...")
    client.clear_cache()
    
    # Third search (after cache clear)
    print(f"🔍 Third search for {email} (after cache clear)...")
    start_time = datetime.now()
    result3 = client.search_email(email)
    time3 = (datetime.now() - start_time).total_seconds()
    print(f"   Time taken: {time3:.3f}s")
    print(f"   Results: {result3.total_results}")

def demonstrate_phone_formats(client):
    """Demonstrate different phone number formats."""
    print("\n" + "="*60)
    print("PHONE NUMBER FORMATS")
    print("="*60)
    
    phone = "+1234567890"
    formats = [
        ("international", PhoneFormat.INTERNATIONAL),
        ("national", PhoneFormat.NATIONAL),
        ("e164", PhoneFormat.E164),
    ]
    
    for format_name, format_enum in formats:
        print(f"\n📞 Searching with {format_name} format...")
        try:
            results = client.search_phone(phone, phone_format=format_name)
            for i, result in enumerate(results, 1):
                print(f"   Result {i}: {result.phone.number}")
                print(f"   Format: {format_name}")
        except Exception as e:
            print(f"   ❌ Error: {e}")

def demonstrate_error_handling(client):
    """Demonstrate comprehensive error handling."""
    print("\n" + "="*60)
    print("ERROR HANDLING DEMONSTRATION")
    print("="*60)
    
    # Test cases for different error scenarios
    test_cases = [
        ("Invalid email", "invalid-email", client.search_email),
        ("Invalid phone", "invalid-phone", client.search_phone),
        ("Invalid domain", "invalid-domain", client.search_domain),
        ("Empty email", "", client.search_email),
        ("Empty phone", "", client.search_phone),
        ("Empty domain", "", client.search_domain),
    ]
    
    for test_name, test_input, test_func in test_cases:
        print(f"\n🧪 Testing: {test_name}")
        print(f"   Input: '{test_input}'")
        
        try:
            result = test_func(test_input)
            print(f"   ✅ Success: {type(result).__name__}")
        except ValidationError as e:
            print(f"   ❌ Validation Error: {e}")
        except InsufficientBalanceError as e:
            print(f"   ❌ Insufficient Balance: {e}")
            print(f"      Current: {e.current_balance}, Required: {e.required_credits}")
        except AuthenticationError as e:
            print(f"   ❌ Authentication Error: {e}")
        except RateLimitError as e:
            print(f"   ❌ Rate Limit Error: {e}")
        except ServerError as e:
            print(f"   ❌ Server Error: {e}")
        except NetworkError as e:
            print(f"   ❌ Network Error: {e}")
        except TimeoutError as e:
            print(f"   ❌ Timeout Error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected Error: {e}")

def demonstrate_batch_operations(client):
    """Demonstrate batch operations with error handling."""
    print("\n" + "="*60)
    print("BATCH OPERATIONS")
    print("="*60)
    
    # Test data
    emails = [
        "john.doe@example.com",
        "jane.smith@example.com",
        "invalid-email",
        "bob.wilson@example.com",
    ]
    
    phones = [
        "+1234567890",
        "+1987654321",
        "invalid-phone",
        "+1555123456",
    ]
    
    domains = [
        "example.com",
        "test-domain.com",
        "invalid-domain",
        "sample.org",
    ]
    
    print("\n📧 Batch email searches:")
    successful_emails = []
    failed_emails = []
    
    for email in emails:
        try:
            result = client.search_email(email)
            successful_emails.append((email, result))
            print(f"   ✅ {email}: {result.total_results} results")
        except Exception as e:
            failed_emails.append((email, e))
            print(f"   ❌ {email}: {e}")
    
    print(f"\n   Summary: {len(successful_emails)} successful, {len(failed_emails)} failed")
    
    print("\n📞 Batch phone searches:")
    successful_phones = []
    failed_phones = []
    
    for phone in phones:
        try:
            results = client.search_phone(phone)
            for result in results:
                print(f"   📱 Phone: {result.phone.number}")
                print(f"   💰 Search Cost: ${result.search_cost}")
            successful_phones.append((phone, results))
            print(f"   ✅ {phone}: {len(results)} results")
        except Exception as e:
            failed_phones.append((phone, e))
            print(f"   ❌ {phone}: {e}")
    
    print(f"\n   Summary: {len(successful_phones)} successful, {len(failed_phones)} failed")
    
    print("\n🌐 Batch domain searches:")
    successful_domains = []
    failed_domains = []
    
    for domain in domains:
        try:
            result = client.search_domain(domain)
            successful_domains.append((domain, result))
            print(f"   ✅ {domain}: {result.total_results} results")
        except Exception as e:
            failed_domains.append((domain, e))
            print(f"   ❌ {domain}: {e}")
    
    print(f"\n   Summary: {len(successful_domains)} successful, {len(failed_domains)} failed")

def demonstrate_context_manager():
    """Demonstrate context manager usage."""
    print("\n" + "="*60)
    print("CONTEXT MANAGER DEMONSTRATION")
    print("="*60)
    
    config = SearchAPIConfig(
        api_key="your-api-key",
        debug_mode=True,
        enable_caching=True,
    )
    
    print("🔧 Using context manager for automatic resource cleanup...")
    
    with SearchAPI(config=config) as client:
        print("   ✅ Client initialized")
        
        try:
            # Check balance
            balance = client.get_balance()
            print(f"   💰 Balance: {balance}")
            
            # Get access logs
            access_logs = client.get_access_logs()
            print(f"   📊 Access logs: {len(access_logs)} entries")
            
            # Perform a search
            result = client.search_email("michael.campbell@gmail.com")
            print(f"   📧 Search completed: {result.total_results} results")
            print("\nPhone Numbers:")
            for i, phone in enumerate(result.phone_numbers, 1):
                print(f"  {i}. {phone.number}")
            
            print("\nAdditional Emails:")
            for email in result.emails:
                print(f"  - {email}")
            
        except Exception as e:
            print(f"   ❌ Error during operation: {e}")
    
    print("   ✅ Client automatically closed")

def main():
    """Main function demonstrating advanced usage."""
    print("🚀 ADVANCED SEARCH API USAGE DEMONSTRATION")
    print("="*60)
    
    # Setup logging
    setup_logging()
    
    # Create client with advanced configuration
    config = SearchAPIConfig(
        api_key="your-api-key",
        debug_mode=False,
        enable_caching=True,
        cache_ttl=1800,  # 30 minutes
        max_cache_size=500,
        timeout=120,  # 2 minutes
        max_retries=5,
    )
    
    client = SearchAPI(config=config)
    
    try:
        # Demonstrate various features
        demonstrate_balance_management(client)
        demonstrate_access_logs(client)
        demonstrate_caching(client)
        demonstrate_phone_formats(client)
        demonstrate_error_handling(client)
        demonstrate_batch_operations(client)
        
        # Demonstrate context manager
        demonstrate_context_manager()
        
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
    finally:
        # Clean up
        client.close()
        print("\n🧹 Resources cleaned up")

if __name__ == "__main__":
    main() 
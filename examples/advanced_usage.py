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
            
        # Check for domain search
        domain_search_cost = 0.0025
        if balance.current_balance < domain_search_cost:
            print(f"⚠️  Warning: Insufficient balance for 1 domain search")
            print(f"   Current: ${balance.current_balance:.4f}, Required: ${domain_search_cost:.4f}")
        else:
            print(f"✅ Sufficient balance for 1 domain search")
            
        # Check for search with all features enabled
        max_search_cost = 0.0025 + 0.0015 + 0.0015 + 0.0005 + 0.0030  # base + house + extra + carrier + tlo
        if balance.current_balance < max_search_cost:
            print(f"⚠️  Warning: Insufficient balance for search with all features")
            print(f"   Current: ${balance.current_balance:.4f}, Required: ${max_search_cost:.4f}")
        else:
            print(f"✅ Sufficient balance for search with all features")
            
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

def demonstrate_tlo_enrichment(client):
    """Demonstrate TLO enrichment features."""
    print("\n" + "="*60)
    print("TLO ENRICHMENT DEMONSTRATION")
    print("="*60)
    
    email = "michael.campbell@gmail.com"
    
    print(f"🔍 Searching for {email} with TLO enrichment...")
    try:
        result = client.search_email(
            email,
            house_value=True,
            extra_info=True,
            carrier_info=True,
            tlo_enrichment=True
        )
        
        print(f"✅ Search completed")
        print(f"💰 Total Cost: ${result.search_cost:.4f}")
        
        if result.pricing:
            print(f"\n📊 Cost Breakdown:")
            print(f"   Base Search: ${result.pricing.search_cost:.4f}")
            print(f"   Extra Info: ${result.pricing.extra_info_cost:.4f}")
            print(f"   Zestimate: ${result.pricing.zestimate_cost:.4f}")
            print(f"   Carrier: ${result.pricing.carrier_cost:.4f}")
            print(f"   TLO Enrichment: ${result.pricing.tlo_enrichment_cost:.4f}")
            print(f"   Total: ${result.pricing.total_cost:.4f}")
        
        if result.alternative_names:
            print(f"\n👤 Alternative Names ({len(result.alternative_names)}):")
            for name in result.alternative_names[:5]:
                print(f"   - {name}")
        
        if result.all_names:
            print(f"\n👤 All Name Records ({len(result.all_names)}):")
            for name_record in result.all_names[:3]:
                print(f"   - {name_record.name}")
                if name_record.date_first_seen:
                    print(f"     First seen: {name_record.date_first_seen}")
        
        if result.all_dobs:
            print(f"\n🎂 All DOB Records ({len(result.all_dobs)}):")
            for dob_record in result.all_dobs:
                print(f"   - {dob_record.dob} (Age: {dob_record.age})")
        
        if result.related_persons:
            print(f"\n👥 Related Persons ({len(result.related_persons)}):")
            for person in result.related_persons[:3]:
                print(f"   - {person.name}")
                if person.relationship:
                    print(f"     Relationship: {person.relationship}")
        
        if result.criminal_records:
            print(f"\n⚖️  Criminal Records ({len(result.criminal_records)}):")
            for record in result.criminal_records:
                print(f"   - {record.source_name} ({record.source_state})")
                print(f"     Cases: {len(record.case_numbers)}")
        
        if result.phone_numbers_full:
            print(f"\n📞 Full Phone Details ({len(result.phone_numbers_full)}):")
            for phone in result.phone_numbers_full[:3]:
                print(f"   - {phone.number}")
                if phone.line_type:
                    print(f"     Type: {phone.line_type}")
                if phone.carrier:
                    print(f"     Carrier: {phone.carrier}")
        
        if result.censored_numbers:
            print(f"\n🔒 Censored Numbers ({len(result.censored_numbers)}):")
            for num in result.censored_numbers[:3]:
                print(f"   - {num}")
        
        if result.addresses_structured:
            print(f"\n📍 Structured Addresses ({len(result.addresses_structured)}):")
            for addr in result.addresses_structured[:2]:
                print(f"   - {addr.address}")
                if addr.components and addr.components.county:
                    print(f"     County: {addr.components.county}")
        
    except Exception as e:
        print(f"❌ Error: {e}")

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
                if result.pricing:
                    print(f"   Cost: ${result.pricing.total_cost:.4f}")
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
    total_cost = 0.0
    
    for email in emails:
        try:
            result = client.search_email(email, extra_info=True)
            successful_emails.append((email, result))
            cost = result.pricing.total_cost if result.pricing else result.search_cost
            total_cost += cost
            print(f"   ✅ {email}: {result.total_results} results (${cost:.4f})")
        except Exception as e:
            failed_emails.append((email, e))
            print(f"   ❌ {email}: {e}")
    
    print(f"\n   Summary: {len(successful_emails)} successful, {len(failed_emails)} failed")
    print(f"   Total Cost: ${total_cost:.4f}")
    
    print("\n📞 Batch phone searches:")
    successful_phones = []
    failed_phones = []
    total_cost = 0.0
    
    for phone in phones:
        try:
            results = client.search_phone(phone, carrier_info=True)
            for result in results:
                print(f"   📱 Phone: {result.phone.number}")
                cost = result.pricing.total_cost if result.pricing else result.search_cost
                total_cost += cost
                print(f"   💰 Search Cost: ${cost:.4f}")
                if result.pricing:
                    print(f"      Breakdown: Base=${result.pricing.search_cost:.4f}, Carrier=${result.pricing.carrier_cost:.4f}")
            successful_phones.append((phone, results))
            print(f"   ✅ {phone}: {len(results)} results")
        except Exception as e:
            failed_phones.append((phone, e))
            print(f"   ❌ {phone}: {e}")
    
    print(f"\n   Summary: {len(successful_phones)} successful, {len(failed_phones)} failed")
    print(f"   Total Cost: ${total_cost:.4f}")
    
    print("\n🌐 Batch domain searches:")
    successful_domains = []
    failed_domains = []
    total_cost = 0.0
    
    for domain in domains:
        try:
            result = client.search_domain(domain)
            successful_domains.append((domain, result))
            cost = result.pricing.total_cost if result.pricing else result.search_cost
            total_cost += cost
            print(f"   ✅ {domain}: {result.total_results} results (${cost:.4f})")
        except Exception as e:
            failed_domains.append((domain, e))
            print(f"   ❌ {domain}: {e}")
    
    print(f"\n   Summary: {len(successful_domains)} successful, {len(failed_domains)} failed")
    print(f"   Total Cost: ${total_cost:.4f}")

def demonstrate_context_manager():
    """Demonstrate context manager usage."""
    print("\n" + "="*60)
    print("CONTEXT MANAGER DEMONSTRATION")
    print("="*60)
    
    config = SearchAPIConfig(
        api_key="your-api-key",
        debug_mode=True,
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
            
            # Perform a search with all features
            result = client.search_email(
                "michael.campbell@gmail.com",
                house_value=True,
                extra_info=True,
                carrier_info=True,
                tlo_enrichment=True
            )
            print(f"   📧 Search completed: {result.total_results} results")
            print(f"   💰 Cost: ${result.search_cost:.4f}")
            
            if result.pricing:
                print(f"   💰 Pricing Breakdown: {result.pricing}")
            
            print("\nPhone Numbers:")
            for i, phone in enumerate(result.phone_numbers, 1):
                print(f"  {i}. {phone.number}")
            
            print("\nAdditional Emails:")
            for email in result.emails:
                print(f"  - {email}")
            
            # Show TLO enrichment data if available
            if result.alternative_names:
                print(f"\nAlternative Names: {len(result.alternative_names)} found")
            if result.related_persons:
                print(f"Related Persons: {len(result.related_persons)} found")
            if result.criminal_records:
                print(f"Criminal Records: {len(result.criminal_records)} found")
            
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
        timeout=120,  # 2 minutes
        max_retries=5,
    )
    
    client = SearchAPI(config=config)
    
    try:
        # Demonstrate various features
        demonstrate_balance_management(client)
        demonstrate_access_logs(client)
        demonstrate_tlo_enrichment(client)
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
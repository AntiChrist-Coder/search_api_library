from search_api import SearchAPI, SearchAPIConfig, InsufficientBalanceError, ValidationError
import logging

def main():
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    config = SearchAPIConfig(
        api_key="3e5d94e6c9f5438c94b89eaf432f1111",
        debug_mode=False,
        enable_caching=True,
        timeout=90,
    )
    
    client = SearchAPI(config=config)
    
    try:
        print("Checking account balance...")
        balance = client.get_balance()
        print(f"Current balance: {balance}")
        print(f"Currency: {balance.currency}")
        print(f"Cost per search: ${balance.credit_cost_per_search}")
        print(f"Last updated: {balance.last_updated}")
        
        print("\n" + "="*50)
        print("Access Logs:")
        print("="*50)
        
        access_logs = client.get_access_logs()
        print(f"Total access log entries: {len(access_logs)}")
        
        for i, log in enumerate(access_logs[:5], 1):
            print(f"\n{i}. IP: {log.ip_address}")
            print(f"   Last accessed: {log.last_accessed}")
            if log.user_agent:
                print(f"   User Agent: {log.user_agent}")
            if log.endpoint:
                print(f"   Endpoint: {log.endpoint}")
            if log.method:
                print(f"   Method: {log.method}")
            if log.status_code:
                print(f"   Status Code: {log.status_code}")
            if log.response_time:
                print(f"   Response Time: {log.response_time:.3f}s")
        
        print("\n" + "="*50)
        print("Searching by email:")
        print("="*50)
        
        result = client.search_email(
            "michael.campbell@gmail.com",
            include_house_value=True,
            include_extra_info=True,
            phone_format="international"
        )
        
        print(f"Email: {result.email}")
        print(f"Email Valid: {result.email_valid}")
        print(f"Email Type: {result.email_type}")
        print(f"Search Cost: ${result.search_cost}")
        
        if result.person:
            print(f"Name: {result.person.name}")
            print(f"DOB: {result.person.dob}")
            print(f"Age: {result.person.age}")
        
        print(f"Total Results: {result.total_results}")
        
        print("\nAddresses:")
        for i, addr in enumerate(result.addresses, 1):
            print(f"  {i}. {addr}")
            if addr.zestimate:
                print(f"     Zestimate: ${addr.zestimate:,.2f}")
        
        print("\nPhone Numbers:")
        for i, phone in enumerate(result.phone_numbers, 1):
            print(f"  {i}. {phone.number}")
        
        print("\nAdditional Emails:")
        for email in result.emails:
            print(f"  - {email}")
        
        print("\n" + "="*50)
        print("Searching by phone:")
        print("="*50)
        
        phone_results = client.search_phone(
            "+14803658262",
            include_house_value=False,
            include_extra_info=False,
            phone_format="international"
        )
        
        for i, result in enumerate(phone_results, 1):
            print(f"\nResult {i}:")
            print(f"  Phone: {result.phone.number}")
            print(f"  Search Cost: ${result.search_cost}")
            
            if result.person:
                print(f"  Name: {result.person.name}")
                print(f"  DOB: {result.person.dob}")
                print(f"  Age: {result.person.age}")
            
            print(f"  Total Results: {result.total_results}")
            
            print("  Addresses:")
            for addr in result.addresses:
                print(f"    - {addr}")
                if addr.zestimate:
                    print(f"      Zestimate: ${addr.zestimate:,.2f}")
            
            print("  Phone Numbers:")
            for phone in result.phone_numbers:
                print(f"    - {phone.number}")
        
        print("\n" + "="*50)
        print("Searching by domain:")
        print("="*50)
        
        domain_result = client.search_domain("example.com")
        print(f"Domain: {domain_result.domain}")
        print(f"Domain Valid: {domain_result.domain_valid}")
        print(f"Total Results: {domain_result.total_results}")
        print(f"Search Cost: ${domain_result.search_cost}")
        
        print("\nResults:")
        for i, email_result in enumerate(domain_result.results, 1):
            print(f"\n  Result {i}:")
            print(f"    Email: {email_result.email}")
            print(f"    Email Valid: {email_result.email_valid}")
            print(f"    Email Type: {email_result.email_type}")
            
            if email_result.person:
                print(f"    Name: {email_result.person.name}")
            
            print(f"    Total Results: {email_result.total_results}")
            
            print("    Addresses:")
            for addr in email_result.addresses:
                print(f"      - {addr}")
            
            print("    Phone Numbers:")
            for phone in email_result.phone_numbers:
                print(f"      - {phone.number}")
        
        print("\n" + "="*50)
        print("Error Handling Examples:")
        print("="*50)
        
        try:
            client.search_email("invalid-email")
        except ValidationError as e:
            print(f"Validation Error: {e}")
        
        try:
            client.search_phone("invalid-phone")
        except ValidationError as e:
            print(f"Validation Error: {e}")
        
        try:
            client.search_domain("invalid-domain")
        except ValidationError as e:
            print(f"Validation Error: {e}")
        
    except InsufficientBalanceError as e:
        print(f"Insufficient Balance Error: {e}")
        print(f"Current Balance: {e.current_balance}")
        print(f"Required Credits: {e.required_credits}")
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        # Clean up resources
        client.close()

if __name__ == "__main__":
    main() 
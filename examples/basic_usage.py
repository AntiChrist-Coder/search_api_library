from search_api import SearchAPI, SearchAPIConfig, InsufficientBalanceError, ValidationError
import logging

def main():
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    config = SearchAPIConfig(
        api_key="your-api-key",
        debug_mode=False,
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
        
        access_logs = client.get_access_logs(limit=50)
        print(f"Total access log entries: {len(access_logs)}")
        
        for i, log in enumerate(access_logs[:5], 1):
            print(f"\n{i}. IP: {log.ip_address}")
            print(f"   Last accessed: {log.last_accessed}")
            if log.search_type:
                print(f"   Search type: {log.search_type}, Cost: ${log.search_cost:.4f}" if log.search_cost else f"   Search type: {log.search_type}")
            if log.user_agent:
                print(f"   User Agent: {log.user_agent}")
            if log.endpoint:
                print(f"   Endpoint: {log.endpoint}")
        
        # Usage stats and cache stats
        stats = client.get_usage_stats()
        print(f"\nUsage: today {stats.today_searches} searches (${stats.today_cost:.4f}), total {stats.total_searches} (${stats.total_cost:.4f})")
        cache_stats = client.get_cache_stats()
        print(f"Cache stats: {cache_stats}")
        
        # Available recovery modules (for email recovery verification)
        recovery = client.get_recovery_modules()
        print(f"\nRecovery modules: {[m.module_name for m in recovery.modules]}")
        if recovery.pricing:
            print(f"Recovery pricing: {recovery.pricing}")
        
        print("\n" + "="*50)
        print("Searching by email:")
        print("="*50)
        
        result = client.search_email(
            "michael.campbell@gmail.com",
            house_value=True,
            extra_info=True,
            carrier_info=True,
            tlo_enrichment=True,
            recovery_check=False,  # Set True to verify phone numbers via recovery modules
            # recovery_modules={"module_order": ["yahoo", "outlook"], "enabled_modules": ["yahoo", "outlook"]},
            phone_format="international"
        )
        
        print(f"Email: {result.email}")
        print(f"Email Valid: {result.email_valid}")
        print(f"Email Type: {result.email_type}")
        print(f"Search Cost: ${result.search_cost}")
        
        # Display detailed pricing breakdown
        if result.pricing:
            print(f"\n💰 Pricing Breakdown:")
            print(f"   Base Search: ${result.pricing.search_cost:.4f}")
            print(f"   Extra Info: ${result.pricing.extra_info_cost:.4f}")
            print(f"   Zestimate: ${result.pricing.zestimate_cost:.4f}")
            print(f"   Carrier: ${result.pricing.carrier_cost:.4f}")
            print(f"   TLO Enrichment: ${result.pricing.tlo_enrichment_cost:.4f}")
            if result.pricing.recovery_check_cost:
                print(f"   Recovery Check: ${result.pricing.recovery_check_cost:.4f}")
            print(f"   Total: ${result.pricing.total_cost:.4f}")
        
        if result.recovery_check:
            print(f"\n📱 Recovery Check: matched={result.recovery_check.matched}, matched_number={result.recovery_check.matched_number}, modules_used={result.recovery_check.modules_used}")
        
        if result.person:
            print(f"\nName: {result.person.name}")
            print(f"DOB: {result.person.dob}")
            print(f"Age: {result.person.age}")
            if result.person.gender:
                print(f"Gender: {result.person.gender}")
        
        # Extra-info enrichment (when extra_info=True)
        if result.location_metro:
            print(f"Location/Metro: {result.location_metro}")
        if result.companies:
            print("\nCompanies:")
            for c in result.companies:
                print(f"  - {c.company_name}" + (f" ({c.position})" if c.position else ""))
        if result.industry:
            print(f"Industry: {result.industry}")
        if result.linkedin_url:
            print(f"LinkedIn: {result.linkedin_url}")
        if result.social_media_identifiers:
            print("Social: " + ", ".join(f"{s.platform}={s.identifier}" for s in result.social_media_identifiers[:3]))
        if result.education:
            print("Education:")
            for e in result.education:
                print(f"  - {e.school_name}" + (f" ({e.start_date}-{e.end_date})" if e.start_date or e.end_date else ""))
        
        if result.pagination:
            print(f"\nPagination: page {result.pagination.get('current_page')}, total {result.pagination.get('total_results')}")
        
        print(f"\nTotal Results: {result.total_results}")
        
        print("\n📍 Addresses:")
        for i, addr in enumerate(result.addresses, 1):
            print(f"  {i}. {addr}")
            if addr.zestimate:
                print(f"     Zestimate: ${addr.zestimate:,.2f}")
        
        # Display structured addresses if available
        if result.addresses_structured:
            print("\n📍 Structured Addresses:")
            for i, addr in enumerate(result.addresses_structured, 1):
                print(f"  {i}. {addr.address}")
                if addr.components:
                    comp = addr.components
                    if comp.city:
                        print(f"     City: {comp.city}")
                    if comp.state:
                        print(f"     State: {comp.state} ({comp.state_code})")
                    if comp.county:
                        print(f"     County: {comp.county}")
                    if comp.zip_code:
                        print(f"     ZIP: {comp.zip_code}")
        
        print("\n📞 Phone Numbers:")
        for i, phone in enumerate(result.phone_numbers, 1):
            print(f"  {i}. {phone.number}")
            if phone.carrier:
                print(f"     Carrier: {phone.carrier}")
        
        # Display full phone number info if available
        if result.phone_numbers_full:
            print("\n📞 Full Phone Number Details:")
            for i, phone in enumerate(result.phone_numbers_full, 1):
                print(f"  {i}. {phone.number}")
                if phone.line_type:
                    print(f"     Type: {phone.line_type}")
                if phone.carrier:
                    print(f"     Carrier: {phone.carrier}")
                if phone.is_spam_report is not None:
                    print(f"     Spam Report: {phone.is_spam_report}")
        
        # Display censored numbers if available
        if result.censored_numbers:
            print("\n🔒 Censored Phone Numbers:")
            for num in result.censored_numbers:
                print(f"  - {num}")
        
        print("\n📧 Additional Emails:")
        for email in result.emails:
            print(f"  - {email}")
        
        # Display other emails if available
        if result.other_emails:
            print("\n📧 Other Emails:")
            for email in result.other_emails:
                print(f"  - {email}")
        
        # Display alternative names if available
        if result.alternative_names:
            print("\n👤 Alternative Names:")
            for name in result.alternative_names:
                print(f"  - {name}")
        
        # Display all names with dates if available
        if result.all_names:
            print("\n👤 All Name Records:")
            for name_record in result.all_names:
                print(f"  - {name_record.name}")
                if name_record.first or name_record.last:
                    print(f"    ({name_record.first} {name_record.middle or ''} {name_record.last})".strip())
        
        # Display all DOBs if available
        if result.all_dobs:
            print("\n🎂 All Date of Birth Records:")
            for dob_record in result.all_dobs:
                print(f"  - {dob_record.dob} (Age: {dob_record.age})")
        
        # Display related persons if available
        if result.related_persons:
            print("\n👥 Related Persons:")
            for person in result.related_persons:
                print(f"  - {person.name}")
                if person.relationship:
                    print(f"    Relationship: {person.relationship}")
                if person.age:
                    print(f"    Age: {person.age}")
        
        # Display criminal records if available
        if result.criminal_records:
            print("\n⚖️  Criminal Records:")
            for record in result.criminal_records:
                print(f"  Source: {record.source_name} ({record.source_state})")
                for crime in record.crimes:
                    if crime.crime_type:
                        print(f"    Type: {crime.crime_type}")
                    if crime.court:
                        print(f"    Court: {crime.court}")
        
        # Display confirmed numbers if available
        if result.confirmed_numbers:
            print("\n✅ Confirmed Phone Numbers:")
            for num in result.confirmed_numbers:
                print(f"  - {num}")
        
        print("\n" + "="*50)
        print("Searching by phone:")
        print("="*50)
        
        phone_results = client.search_phone(
            "+14803658262",
            house_value=True,
            extra_info=True,
            carrier_info=True,
            tlo_enrichment=True,
            phone_format="international"
        )
        
        for i, result in enumerate(phone_results, 1):
            print(f"\nResult {i}:")
            print(f"  Phone: {result.phone.number}")
            print(f"  Search Cost: ${result.search_cost}")
            
            # Display detailed pricing breakdown
            if result.pricing:
                print(f"  💰 Pricing: {result.pricing}")
            
            if result.person:
                print(f"  Name: {result.person.name}")
                print(f"  DOB: {result.person.dob}")
                print(f"  Age: {result.person.age}")
                if result.person.gender:
                    print(f"  Gender: {result.person.gender}")
            if result.location_metro:
                print(f"  Location: {result.location_metro}")
            if result.companies:
                print("  Companies: " + ", ".join(c.company_name for c in result.companies[:2]))
            
            print(f"  Total Results: {result.total_results}")
            
            print("  📍 Addresses:")
            for addr in result.addresses:
                print(f"    - {addr}")
                if addr.zestimate:
                    print(f"      Zestimate: ${addr.zestimate:,.2f}")
            
            # Display structured addresses if available
            if result.addresses_structured:
                print("  📍 Structured Addresses:")
                for addr in result.addresses_structured:
                    print(f"    - {addr.address}")
            
            print("  📞 Phone Numbers:")
            for phone in result.phone_numbers:
                print(f"    - {phone.number}")
            
            # Display TLO enrichment fields if available
            if result.censored_numbers:
                print("  🔒 Censored Numbers:")
                for num in result.censored_numbers:
                    print(f"    - {num}")
            
            if result.alternative_names:
                print("  👤 Alternative Names:")
                for name in result.alternative_names:
                    print(f"    - {name}")
            
            if result.related_persons:
                print("  👥 Related Persons:")
                for person in result.related_persons:
                    print(f"    - {person.name}")
                    if person.relationship:
                        print(f"      Relationship: {person.relationship}")
        
        print("\n" + "="*50)
        print("Searching by company:")
        print("="*50)
        
        company_result = client.search_company("Acme Corp", country="US", page=1, limit=50)
        print(f"Company: {company_result.company}")
        print(f"Total Results: {company_result.total_results}")
        print(f"Search Cost: ${company_result.search_cost}")
        for i, contact in enumerate(company_result.results[:3], 1):
            print(f"  {i}. {contact.person.name if contact.person else 'N/A'} - {contact.emails[:1]}")
        
        print("\n" + "="*50)
        print("Searching by domain:")
        print("="*50)
        
        domain_result = client.search_domain("example.com", page=1, limit=100)
        print(f"Domain: {domain_result.domain}")
        print(f"Domain Valid: {domain_result.domain_valid}")
        print(f"Total Results: {domain_result.total_results}")
        print(f"Search Cost: ${domain_result.search_cost}")
        
        # Display detailed pricing breakdown
        if domain_result.pricing:
            print(f"\n💰 Pricing Breakdown:")
            print(f"   Base Search: ${domain_result.pricing.search_cost:.4f}")
            print(f"   Total: ${domain_result.pricing.total_cost:.4f}")
        
        print("\nResults:")
        for i, email_result in enumerate(domain_result.results, 1):
            print(f"\n  Result {i}:")
            print(f"    Email: {email_result.email}")
            print(f"    Email Valid: {email_result.email_valid}")
            print(f"    Email Type: {email_result.email_type}")
            
            if email_result.person:
                print(f"    Name: {email_result.person.name}")
                if email_result.person.gender:
                    print(f"    Gender: {email_result.person.gender}")
            if email_result.companies:
                print(f"    Companies: {[c.company_name for c in email_result.companies]}")
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
        
        try:
            client.search_company("")
        except ValidationError as e:
            print(f"Validation Error (empty company): {e}")
        
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
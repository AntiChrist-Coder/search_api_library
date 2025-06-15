from search_api import SearchAPI

def main():
    # Initialize the client with your API key
    client = SearchAPI(api_key="your_api_key")

    try:
        # Search by email
        print("\nSearching by email:")
        result = client.search_email(
            "example@domain.com",
            include_house_value=True,
            include_extra_info=True
        )
        print(f"Name: {result.name}")
        print(f"DOB: {result.dob}")
        print("Addresses:")
        for addr in result.addresses:
            print(f"  - {addr}")
            if addr.zestimate:
                print(f"    Zestimate: ${addr.zestimate:,.2f}")
        print("Phone Numbers:")
        for phone in result.phone_numbers:
            print(f"  - {phone}")

        # Search by phone
        print("\nSearching by phone:")
        result = client.search_phone(
            "+1234567890",
            include_house_value=True,
            include_extra_info=True
        )
        print(f"Name: {result.name}")
        print(f"DOB: {result.dob}")
        print("Addresses:")
        for addr in result.addresses:
            print(f"  - {addr}")
            if addr.zestimate:
                print(f"    Zestimate: ${addr.zestimate:,.2f}")
        print("Phone Numbers:")
        for phone in result.phone_numbers:
            print(f"  - {phone}")

        # Search by domain
        print("\nSearching by domain:")
        result = client.search_domain("example.com")
        print(f"Domain: {result.domain}")
        print(f"Total Results: {result.total_results}")
        print("Results:")
        for email_result in result.results:
            print(f"\nEmail: {email_result.email}")
            print(f"Name: {email_result.name}")
            print("Addresses:")
            for addr in email_result.addresses:
                print(f"  - {addr}")
            print("Phone Numbers:")
            for phone in email_result.phone_numbers:
                print(f"  - {phone}")

    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    main() 
from search_api import SearchAPI

def main():
    # Initialize the client with your API key
    client = SearchAPI(api_key="your_api_key")

    try:
        # Example 1: Search by email with both options
        print("\nSearching by email with both extra info and house value:")
        result = client.search_email(
            "example@domain.com",
            include_house_value=True,  # Get house values for addresses
            include_extra_info=True    # Get additional information
        )
        
        print(f"Name: {result.name}")
        print(f"DOB: {result.dob}")
        
        # Print addresses with Zestimates
        print("\nAddresses with Zestimates:")
        for addr in result.addresses:
            print(f"  - {addr}")
            if addr.zestimate:
                print(f"    Zestimate: ${addr.zestimate:,.2f}")
        
        # Print phone numbers
        print("\nPhone Numbers:")
        for phone in result.phone_numbers:
            print(f"  - {phone}")
        
        # Print extra information if available
        if result.extra_info:
            print("\nExtra Information:")
            for key, value in result.extra_info.items():
                print(f"  {key}: {value}")

        # Example 2: Search by phone with both options
        print("\nSearching by phone with both extra info and house value:")
        result = client.search_phone(
            "+1234567890",
            include_house_value=True,  # Get house values for addresses
            include_extra_info=True    # Get additional information
        )
        
        print(f"Name: {result.name}")
        print(f"DOB: {result.dob}")
        
        # Print addresses with Zestimates
        print("\nAddresses with Zestimates:")
        for addr in result.addresses:
            print(f"  - {addr}")
            if addr.zestimate:
                print(f"    Zestimate: ${addr.zestimate:,.2f}")
        
        # Print phone numbers
        print("\nPhone Numbers:")
        for phone in result.phone_numbers:
            print(f"  - {phone}")
        
        # Print extra information if available
        if result.extra_info:
            print("\nExtra Information:")
            for key, value in result.extra_info.items():
                print(f"  {key}: {value}")

    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    main() 
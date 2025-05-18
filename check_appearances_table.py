import os
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

# Initialize Supabase client
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

def check_appearances_table():
    print("\n--- Detailed Appearances Table Structure ---")
    
    try:
        # We'll use a player ID from the existing data
        player_id = "532bcbb3-1610-41a5-a890-1cffeeac8154"  # LUTSHAREL GEERTRUIDA
        match_id = "f5556963-4258-4e21-ae93-135919f6a2fa"  # Match ID from previous script
        
        # Try different combinations of fields
        possible_structures = [
            {"player_id": player_id, "match_id": match_id, "played": True},
            {"player_id": player_id, "match_id": match_id, "appearance": True},
            {"player_id": player_id, "match_id": match_id}
        ]
        
        for structure in possible_structures:
            try:
                print(f"\nTrying structure: {structure}")
                result = supabase.table("appearances").insert(structure).execute()
                
                if hasattr(result, 'data') and result.data:
                    print("Success! Structure accepted.")
                    print("\nAppearances table columns:")
                    
                    # Display the returned record to see all columns (including defaults)
                    for key in result.data[0].keys():
                        print(f"  - {key}")
                        
                    # Now delete the test record
                    id_to_delete = result.data[0]['id']
                    print(f"\nDeleting test record with ID: {id_to_delete}")
                    supabase.table("appearances").delete().eq('id', id_to_delete).execute()
                    
                    # We found a working structure, so break
                    break
            except Exception as e:
                print(f"This structure failed: {str(e)}")
                continue
        
        # Try to get any existing records as a last resort
        print("\nAttempting to query any existing records from appearances table...")
        result = supabase.table("appearances").select("*").execute()
        
        if hasattr(result, 'data') and result.data and len(result.data) > 0:
            print("\nFound existing record - columns structure:")
            for key in result.data[0].keys():
                print(f"  - {key}")
        else:
            print("No existing records found in the appearances table.")
            
    except Exception as e:
        print(f"Error: {str(e)}")
        print("\nCould not determine appearances table structure through any method.")

def main():
    check_appearances_table()

if __name__ == "__main__":
    main() 
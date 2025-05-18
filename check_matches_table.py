import os
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

# Initialize Supabase client
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

def check_matches_table():
    print("\n--- Detailed Matches Table Structure ---")
    
    try:
        # Use a simpler approach - attempt to insert with minimal fields
        home_team_id = "c08b8681-ed7f-4b38-b384-9457be8cca3b"  # AC MILAN
        away_team_id = "dbb943ae-778a-476b-bb6c-d8141db338e7"  # ARSENAL FC
        
        # Try different combinations of fields
        possible_structures = [
            {"home_team_id": home_team_id, "away_team_id": away_team_id},
            {"home_team": home_team_id, "away_team": away_team_id},
            {"match_day": "MD1", "home_team_id": home_team_id, "away_team_id": away_team_id}
        ]
        
        for structure in possible_structures:
            try:
                print(f"\nTrying structure: {structure}")
                result = supabase.table("matches").insert(structure).execute()
                
                if hasattr(result, 'data') and result.data:
                    print("Success! Structure accepted.")
                    print("\nMatches table columns:")
                    
                    # Display the returned record to see all columns (including defaults)
                    for key in result.data[0].keys():
                        print(f"  - {key}")
                        
                    # Now delete the test record
                    id_to_delete = result.data[0]['id']
                    print(f"\nDeleting test record with ID: {id_to_delete}")
                    supabase.table("matches").delete().eq('id', id_to_delete).execute()
                    
                    # We found a working structure, so break
                    break
            except Exception as e:
                print(f"This structure failed: {str(e)}")
                continue
        
        # Try to get any existing records as a last resort
        print("\nAttempting to query any existing records from matches table...")
        result = supabase.table("matches").select("*").execute()
        
        if hasattr(result, 'data') and result.data and len(result.data) > 0:
            print("\nFound existing record - columns structure:")
            for key in result.data[0].keys():
                print(f"  - {key}")
        else:
            print("No existing records found in the matches table.")
            
    except Exception as e:
        print(f"Error: {str(e)}")
        print("\nCould not determine matches table structure through any method.")

def main():
    check_matches_table()

if __name__ == "__main__":
    main() 
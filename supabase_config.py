import os
from supabase import create_client
from dotenv import load_dotenv
import re
from datetime import datetime
import traceback

# Load environment variables
load_dotenv()

# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase credentials not found. Make sure SUPABASE_URL and SUPABASE_KEY are in your .env file")

# Initialize Supabase client
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Function to initialize Supabase connection and return the client
def get_supabase_client():
    """
    Returns initialized Supabase client
    """
    return supabase

# Helper function to get all teams
def get_teams():
    """
    Get all teams from Supabase database
    """
    response = supabase.table("teams").select("id, name").order("name").execute()
    return response.data

# Helper function to get players for a team
def get_players_by_team(team_id):
    """
    Get all players for a specific team
    """
    response = supabase.table("players").select("*").eq("team_id", team_id).execute()
    return response.data

# Helper function to get player by ID
def get_player_by_id(player_id):
    """
    Get player details by ID
    """
    response = supabase.table("players").select("*").eq("id", player_id).execute()
    if response.data:
        return response.data[0]
    return None

# Helper function to get player by name and team
def get_player_by_name_and_team(player_name, team_id):
    """
    Get player by name and team ID
    """
    response = supabase.table("players").select("*").eq("name", player_name).eq("team_id", team_id).execute()
    if response.data:
        return response.data[0]
    return None

# Helper function to update player appearance
def update_player_appearance(player_id, match_day, appeared=True, match_id=None):
    """
    Update or create a player appearance record and update player's total appearances
    """
    try:
        # Check if an appearance record already exists
        existing = supabase.table("appearances")\
            .select("id, appeared")\
            .eq("player_id", player_id)\
            .eq("match_day", match_day)\
            .execute()
        
        new_appearance = False
        was_appeared = False
        
        if existing.data:
            # Get current appeared status
            was_appeared = existing.data[0].get("appeared", False)
            
            # Update existing record
            response = supabase.table("appearances")\
                .update({"appeared": appeared, "match_id": match_id})\
                .eq("id", existing.data[0]["id"])\
                .execute()
                
            # Debug output
            print(f"Updated appearance for player {player_id}, match_day {match_day}, appeared: {appeared}")
            print(f"Previous state: {was_appeared}, New state: {appeared}")
        else:
            # Create new record
            response = supabase.table("appearances")\
                .insert({"player_id": player_id, "match_day": match_day, "appeared": appeared, "match_id": match_id})\
                .execute()
            
            # Mark as new appearance if player appeared
            if appeared:
                new_appearance = True
                
            # Debug output
            print(f"Created new appearance for player {player_id}, match_day {match_day}, appeared: {appeared}")
        
        # If this is a new appearance and the player appeared, increment their total appearances
        if new_appearance:
            try:
                # Get current player data
                player_data = get_player_by_id(player_id)
                if player_data:
                    # Calculate new total
                    current_total = player_data.get("total_appearances", 0) or 0
                    new_total = current_total + 1
                    
                    # Update player record
                    supabase.table("players")\
                        .update({"total_appearances": new_total})\
                        .eq("id", player_id)\
                        .execute()
                    
                    print(f"Updated player {player_data.get('name')} total appearances to {new_total}")
            except Exception as e:
                print(f"Error updating player total appearances: {str(e)}")
        
        # If the player was marked as appeared but now isn't, decrement the total
        if was_appeared and not appeared:
            try:
                # Get current player data
                player_data = get_player_by_id(player_id)
                if player_data:
                    # Calculate new total (minimum 0)
                    current_total = player_data.get("total_appearances", 0) or 0
                    new_total = max(0, current_total - 1)
                    
                    # Update player record
                    supabase.table("players")\
                        .update({"total_appearances": new_total})\
                        .eq("id", player_id)\
                        .execute()
                    
                    print(f"Updated player {player_data.get('name')} total appearances to {new_total} (decremented)")
            except Exception as e:
                print(f"Error updating player total appearances: {str(e)}")
                
        return response.data
    except Exception as e:
        print(f"Error updating player appearance: {str(e)}")
        traceback.print_exc()
        return None

# Function to add new player to a team
def add_new_player(player_name, team_id, position="Unknown", status="Active"):
    """
    Add a new player to the database
    """
    player_data = {
        "name": player_name,
        "team_id": team_id,
        "position": position,
        "status": status,
        "total_appearances": 0
    }
    
    response = supabase.table("players").insert(player_data).execute()
    if response.data:
        return response.data[0]
    return None

# Function to add unmatched player to a separate table
def add_unmatched_player(player_name, team_id, match_day, position="Unknown", match_id=None):
    """
    Add an unmatched player to a separate unmatched_players table
    rather than directly to the team squad
    """
    player_data = {
        "name": player_name,
        "team_id": team_id,
        "match_day": match_day,
        "position": position,
        "match_id": match_id,
        "created_at": datetime.now().isoformat()
    }
    
    # First check if this player already exists in the unmatched table
    response = supabase.table("unmatched_players").select("id") \
        .eq("name", player_name) \
        .eq("team_id", team_id) \
        .eq("match_id", match_id) \
        .execute()
        
    if response.data:
        # Player already exists in unmatched table, just return it
        return response.data[0]
    
    # Add new unmatched player
    response = supabase.table("unmatched_players").insert(player_data).execute()
    if response.data:
        return response.data[0]
    return None

# Function to create a match record
def create_match(home_team_id, away_team_id, match_day):
    """
    Create a new match record
    """
    match_data = {
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "match_day": match_day
    }
    
    response = supabase.table("matches").insert(match_data).execute()
    if response.data:
        return response.data[0]
    return None

# Function to get team by name
def get_team_by_name(team_name):
    """
    Get team by exact name
    """
    response = supabase.table("teams").select("*").eq("name", team_name).execute()
    if response.data:
        return response.data[0]
    return None

# Function to search for team by partial name
def search_teams_by_partial_name(partial_name):
    """
    Search for teams by partial name (case insensitive)
    """
    response = supabase.table("teams").select("*").ilike("name", f"%{partial_name}%").execute()
    return response.data

# Function to get team appearance statistics
def get_team_appearance_stats(team_id):
    """
    Get appearance statistics for all players in a team
    Returns a list of players with their appearance counts and calculated earnings
    """
    try:
        # First get all players for this team
        players = get_players_by_team(team_id)
        
        if not players:
            return []
        
        # For each player, get their appearances
        for player in players:
            player_id = player["id"]
            
            # Get appearances for this player
            appearances = supabase.table("appearances")\
                .select("*")\
                .eq("player_id", player_id)\
                .eq("appeared", True)\
                .execute()
            
            # Add appearances data to player object
            player["appearances_list"] = appearances.data
            player["appearance_count"] = len(appearances.data)
            
            # Get match days
            match_days = [app["match_day"] for app in appearances.data]
            player["match_days"] = match_days
            
            # Extract numeric value from salary and value fields (format: "20 RC")
            try:
                # Process salary field
                if player.get("salary") is not None:
                    # Convert to string if it's not already
                    salary_str = str(player.get("salary"))
                    # Extract the number from the string, preserving decimal points
                    salary_match = re.search(r'(\d+\.?\d*)', salary_str)
                    if salary_match:
                        player["salary_numeric"] = float(salary_match.group(1))
                        # Keep original value for display
                        player["salary_display"] = salary_str
                    else:
                        player["salary_numeric"] = 0
                        player["salary_display"] = salary_str
                else:
                    player["salary_numeric"] = 0
                    player["salary_display"] = "0 RC"
                
                # Process value field
                if player.get("value") is not None:
                    # Convert to string if it's not already
                    value_str = str(player.get("value"))
                    # Extract the number from the string, preserving decimal points
                    value_match = re.search(r'(\d+\.?\d*)', value_str)
                    if value_match:
                        player["value_numeric"] = float(value_match.group(1))
                        # Keep original value for display
                        player["value_display"] = value_str
                    else:
                        player["value_numeric"] = 0
                        player["value_display"] = value_str
                else:
                    player["value_numeric"] = 0
                    player["value_display"] = "0 RC"
            except Exception as e:
                print(f"Error processing salary/value for player {player.get('name')}: {str(e)}")
                player["salary_numeric"] = 0
                player["value_numeric"] = 0
                player["salary_display"] = player.get("salary", "0 RC")
                player["value_display"] = player.get("value", "0 RC")
            
            # Calculate earnings based on salary and appearances
            salary_per_match = player["salary_numeric"]
            total_salary = float(salary_per_match) * float(player["appearance_count"])
            player["total_earnings"] = total_salary  # Keep this for backward compatibility
            # Always display with one decimal point
            player["total_salary_display"] = f"{total_salary:.1f} RC"
            player["total_earnings_display"] = player["total_salary_display"]  # Keep this for backward compatibility
        
        # Sort players by appearance count (descending)
        players.sort(key=lambda p: p.get("appearance_count", 0), reverse=True)
        
        return players
    
    except Exception as e:
        print(f"Error getting team appearance stats: {str(e)}")
        import traceback
        traceback.print_exc()
        return []

# Function to get match appearance statistics
def get_match_appearance_stats(match_id):
    """
    Get appearance statistics for a specific match
    Returns home and away team players who appeared in the match
    """
    try:
        # First get the match details
        match = supabase.table("matches").select("*").eq("id", match_id).execute()
        
        if not match.data:
            return None
            
        match_data = match.data[0]
        home_team_id = match_data.get("home_team_id")
        away_team_id = match_data.get("away_team_id")
        match_day = match_data.get("match_day")
        
        # Get all appearances for this match in a single query
        all_appearances = supabase.table("appearances")\
            .select("*")\
            .eq("match_id", match_id)\
            .eq("appeared", True)\
            .execute()
            
        if not all_appearances.data:
            return {
                "match": match_data,
                "home_players": [],
                "away_players": [],
                "home_count": 0,
                "away_count": 0
            }
        
        # Get all players that appeared in this match
        player_ids = [app.get("player_id") for app in all_appearances.data if app.get("player_id")]
        
        # Fetch all players in a single query instead of one by one
        all_players = []
        if player_ids:
            # Use the correct syntax for Supabase
            all_players_response = supabase.table("players").select("*").in_("id", player_ids).execute()
            all_players = all_players_response.data
        
        # Create a lookup dictionary for faster player access
        player_lookup = {p["id"]: p for p in all_players}
        
        # Separate home and away players
        home_players = []
        away_players = []
        
        # Process all appearances and combine with player data
        for appearance in all_appearances.data:
            player_id = appearance.get("player_id")
            if not player_id or player_id not in player_lookup:
                continue
                
            # Get player info from the lookup
            player_info = player_lookup[player_id]
                
            # Create combined appearance with player info
            appearance_with_player = {**appearance}
            appearance_with_player["name"] = player_info.get("name")
            appearance_with_player["position"] = player_info.get("position")
            appearance_with_player["value"] = player_info.get("value")
            appearance_with_player["salary"] = player_info.get("salary")
            
            # Process value and salary for display
            try:
                # Process value field
                if player_info.get("value") is not None:
                    value_str = str(player_info.get("value"))
                    appearance_with_player["value_display"] = value_str
                    
                    # Extract numeric value if possible
                    value_match = re.search(r'(\d+\.?\d*)', value_str)
                    if value_match:
                        appearance_with_player["value_numeric"] = float(value_match.group(1))
                    else:
                        appearance_with_player["value_numeric"] = 0
                else:
                    appearance_with_player["value_display"] = "Unknown"
                    appearance_with_player["value_numeric"] = 0
                    
                # Process salary field
                if player_info.get("salary") is not None:
                    salary_str = str(player_info.get("salary"))
                    appearance_with_player["salary_display"] = salary_str
                    
                    # Extract numeric salary if possible
                    salary_match = re.search(r'(\d+\.?\d*)', salary_str)
                    if salary_match:
                        appearance_with_player["salary_numeric"] = float(salary_match.group(1))
                    else:
                        appearance_with_player["salary_numeric"] = 0
                else:
                    appearance_with_player["salary_display"] = "Unknown"
                    appearance_with_player["salary_numeric"] = 0
            except Exception as e:
                print(f"Error processing value/salary for player {player_info.get('name')}: {str(e)}")
                appearance_with_player["value_display"] = "Error"
                appearance_with_player["value_numeric"] = 0
                appearance_with_player["salary_display"] = "Error"
                appearance_with_player["salary_numeric"] = 0
            
            # Add to appropriate team list
            if player_info.get("team_id") == home_team_id:
                home_players.append(appearance_with_player)
            elif player_info.get("team_id") == away_team_id:
                away_players.append(appearance_with_player)
        
        return {
            "match": match_data,
            "home_players": home_players,
            "away_players": away_players,
            "home_count": len(home_players),
            "away_count": len(away_players)
        }
        
    except Exception as e:
        print(f"Error getting match appearance stats: {str(e)}")
        traceback.print_exc()
        return None

# Function to get all matches for a specific team
def get_team_matches(team_id):
    """
    Get all matches where the specified team played (either home or away)
    Returns a list of match objects with player appearance data
    """
    try:
        # Find matches directly through the matches table instead of appearances
        supabase_client = get_supabase_client()
        
        # Get matches where this team was home OR away (more efficient than going through appearances)
        home_matches = supabase_client.table("matches").select("*").eq("home_team_id", team_id).execute()
        away_matches = supabase_client.table("matches").select("*").eq("away_team_id", team_id).execute()
        
        # Combine matches
        all_matches = []
        if home_matches.data:
            all_matches.extend(home_matches.data)
        if away_matches.data:
            all_matches.extend(away_matches.data)
            
        if not all_matches:
            return []
            
        # Create a dictionary to quickly look up matches by ID
        match_dict = {match["id"]: match for match in all_matches}
        
        # Sort by match day
        all_matches.sort(key=lambda m: m.get("match_day", ""))
        
        # Get all players for this team in one query
        players = get_players_by_team(team_id)
        player_dict = {player["id"]: player for player in players}
        
        # Get all match IDs
        match_ids = list(match_dict.keys())
        
        # Get all appearances for these matches in a single query if possible
        match_appearances = {}
        
        # Process in batches if there are many matches to avoid query limitations
        batch_size = 10
        for i in range(0, len(match_ids), batch_size):
            batch_ids = match_ids[i:i+batch_size]
            
            # Use the correct syntax for Supabase - we need to use in() instead of filter()
            batch_appearances = supabase_client.table("appearances")\
                .select("*")\
                .in_("match_id", batch_ids)\
                .eq("appeared", True)\
                .execute()
                
            # Group appearances by match ID
            for appearance in batch_appearances.data:
                match_id = appearance.get("match_id")
                if match_id:
                    if match_id not in match_appearances:
                        match_appearances[match_id] = []
                    match_appearances[match_id].append(appearance)
        
        # Process match details and appearances
        for match in all_matches:
            match_id = match["id"]
            
            # Determine if this team was home or away
            is_home = match.get("home_team_id") == team_id
            match["is_home"] = is_home
            
            # Get opponent team name
            opponent_id = match["away_team_id"] if is_home else match["home_team_id"]
            opponent_team = get_team_by_id(opponent_id)
            opponent_name = opponent_team["name"] if opponent_team else "Unknown Team"
            match["opponent"] = opponent_name
            
            # Get player appearances for this match from the cached data
            player_appearances = []
            if match_id in match_appearances:
                for appearance in match_appearances[match_id]:
                    player_id = appearance.get("player_id")
                    # Only include players from this team
                    if player_id in player_dict:
                        player_info = player_dict[player_id]
                        # Combine appearance data with player info
                        appearance_with_player = {**appearance}
                        appearance_with_player["name"] = player_info.get("name")
                        appearance_with_player["position"] = player_info.get("position")
                        appearance_with_player["value"] = player_info.get("value")
                        player_appearances.append(appearance_with_player)
            
            match["players"] = player_appearances
            match["player_count"] = len(player_appearances)
            
        return all_matches
        
    except Exception as e:
        print(f"Error getting team matches: {str(e)}")
        traceback.print_exc()
        return []

# Function to get team by ID
def get_team_by_id(team_id):
    """
    Get team by ID
    """
    response = supabase.table("teams").select("*").eq("id", team_id).execute()
    if response.data:
        return response.data[0]
    return None

# Function to batch save processing results
def batch_save_to_database(batch_results):
    """
    Save a batch of video processing results to the database
    """
    success_count = 0
    error_count = 0
    created_matches = []
    added_players = 0
    unmatched_players = 0
    updated_appearances = 0
    errors = []
    
    try:
        for result in batch_results:
            try:
                # Get team data
                home_team = result.get('home_team')
                away_team = result.get('away_team')
                match_day = result.get('match_day', 'MD1')
                home_data = result.get('home_data', {})
                away_data = result.get('away_data', {})
                unmatched_home = result.get('unmatched_home', [])
                unmatched_away = result.get('unmatched_away', [])
                # Get match_id if it was already created during processing
                match_id = result.get('match_id')
                
                # Get team IDs
                home_team_data = get_team_by_name(home_team)
                away_team_data = get_team_by_name(away_team)
                
                if not home_team_data or not away_team_data:
                    error_count += 1
                    error_msg = f"Teams not found: {home_team} or {away_team}"
                    errors.append(error_msg)
                    continue
                
                home_team_id = home_team_data["id"]
                away_team_id = away_team_data["id"]
                
                # Create match record if it doesn't exist and wasn't created during processing
                if not match_id:
                    match_exists_response = supabase.table("matches").select("id")\
                        .eq("home_team_id", home_team_id)\
                        .eq("away_team_id", away_team_id)\
                        .eq("match_day", match_day)\
                        .execute()
                        
                    if match_exists_response.data:
                        match_id = match_exists_response.data[0]["id"]
                    else:
                        match_result = create_match(home_team_id, away_team_id, match_day)
                        if match_result:
                            match_id = match_result["id"]
                            created_matches.append({
                                'home_team': home_team,
                                'away_team': away_team,
                                'match_day': match_day,
                                'match_id': match_id
                            })
                
                # Add unmatched home players to the unmatched_players table instead of team squad
                for player_name in unmatched_home:
                    position = result.get('home_positions', {}).get(player_name, "Unknown")
                    unmatched_player = add_unmatched_player(player_name, home_team_id, match_day, position, match_id)
                    if unmatched_player:
                        unmatched_players += 1
                
                # Add unmatched away players to the unmatched_players table
                for player_name in unmatched_away:
                    position = result.get('away_positions', {}).get(player_name, "Unknown")
                    unmatched_player = add_unmatched_player(player_name, away_team_id, match_day, position, match_id)
                    if unmatched_player:
                        unmatched_players += 1
                
                # Update appearances for existing home players
                home_team_players = get_players_by_team(home_team_id)
                for player in home_team_players:
                    player_name = player["name"]
                    if player_name in home_data and home_data[player_name] == 1:
                        update_player_appearance(player["id"], match_day, True, match_id)
                        updated_appearances += 1
                
                # Update appearances for existing away players
                away_team_players = get_players_by_team(away_team_id)
                for player in away_team_players:
                    player_name = player["name"]
                    if player_name in away_data and away_data[player_name] == 1:
                        update_player_appearance(player["id"], match_day, True, match_id)
                        updated_appearances += 1
                
                success_count += 1
                
            except Exception as e:
                error_count += 1
                errors.append(str(e))
                continue
        
        return {
            "success": True,
            "success_count": success_count,
            "error_count": error_count,
            "created_matches": created_matches,
            "added_players": added_players,
            "unmatched_players": unmatched_players,
            "updated_appearances": updated_appearances,
            "errors": errors
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "errors": errors
        }

# Function to get all unmatched players
def get_unmatched_players(match_id=None):
    """
    Get all unmatched players from the database
    Returns a list of unmatched players with team information
    
    Parameters:
    match_id - If provided, only returns unmatched players for this match
    """
    try:
        # Get unmatched players, filtered by match_id if provided
        if match_id:
            response = supabase.table("unmatched_players").select("*").eq("match_id", match_id).execute()
        else:
            response = supabase.table("unmatched_players").select("*").execute()
        
        unmatched_players = response.data
        
        # Add team information to each player
        for player in unmatched_players:
            team_id = player.get("team_id")
            if team_id:
                team = get_team_by_id(team_id)
                if team:
                    player["team_name"] = team.get("name", "Unknown Team")
                else:
                    player["team_name"] = "Unknown Team"
            
            # Add match information if available
            player_match_id = player.get("match_id")
            if player_match_id:
                try:
                    match_data = supabase.table("matches").select("*").eq("id", player_match_id).execute()
                    if match_data.data:
                        match = match_data.data[0]
                        
                        # Get team names for the match
                        home_team = get_team_by_id(match.get("home_team_id", ""))
                        away_team = get_team_by_id(match.get("away_team_id", ""))
                        
                        home_team_name = home_team.get("name", "") if home_team else ""
                        away_team_name = away_team.get("name", "") if away_team else ""
                        
                        player["match_info"] = f"{home_team_name} vs {away_team_name} ({match.get('match_day', '')})"
                except Exception as e:
                    print(f"Error getting match data for player {player.get('name')}: {str(e)}")
        
        # Sort by team name and then by player name
        unmatched_players.sort(key=lambda p: (p.get("team_name", ""), p.get("name", "")))
        
        return unmatched_players
    except Exception as e:
        print(f"Error getting unmatched players: {str(e)}")
        return []

# Function to get unmatched players for a specific team
def get_unmatched_players_by_team(team_id):
    """
    Get all unmatched players for a specific team
    """
    try:
        response = supabase.table("unmatched_players").select("*").eq("team_id", team_id).execute()
        players = response.data
        
        # Add match information if available
        for player in players:
            match_id = player.get("match_id")
            if match_id:
                try:
                    match_data = supabase.table("matches").select("*").eq("id", match_id).execute()
                    if match_data.data:
                        match = match_data.data[0]
                        
                        # Get team names for the match
                        home_team = get_team_by_id(match.get("home_team_id", ""))
                        away_team = get_team_by_id(match.get("away_team_id", ""))
                        
                        home_team_name = home_team.get("name", "") if home_team else ""
                        away_team_name = away_team.get("name", "") if away_team else ""
                        
                        player["match_info"] = f"{home_team_name} vs {away_team_name} ({match.get('match_day', '')})"
                except Exception as e:
                    print(f"Error getting match data for player {player.get('name')}: {str(e)}")
        
        return players
    except Exception as e:
        print(f"Error getting unmatched players for team: {str(e)}")
        return [] 
import os
import cv2
import re
import time
import uuid
import easyocr
import unicodedata
import traceback
import json
import tempfile
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
from werkzeug.utils import secure_filename
from PIL import Image
import pandas as pd
import numpy as np
from openpyxl import load_workbook, Workbook
from fuzzywuzzy import process
from threading import Thread
# Import Cloudinary helper
from cloudinary_helper import upload_file as cloudinary_upload, download_file as cloudinary_download, get_image_as_array, save_cv2_image

# Import Supabase configuration and helpers
from supabase_config import (
    get_teams, get_team_by_name, search_teams_by_partial_name,
    get_players_by_team, get_player_by_id, get_player_by_name_and_team,
    update_player_appearance, add_new_player, create_match,
    get_team_appearance_stats, get_match_appearance_stats, get_team_matches,
    get_team_by_id, get_supabase_client, batch_save_to_database,
    add_unmatched_player, get_unmatched_players, get_unmatched_players_by_team
)

# Handle PIL ANTIALIAS deprecation in newer versions
if not hasattr(Image, 'ANTIALIAS'):
    # For newer Pillow versions (>=9.0.0)
    Image.ANTIALIAS = Image.Resampling.LANCZOS

# Define configuration variables
UPLOAD_FOLDER = 'static/uploads'
FRAMES_FOLDER = 'static/frames'
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv'}
TEMP_EXCEL_PATH = 'static/temp/temp_data.xlsx'
DEFAULT_EXCEL_PATH = 'APPEARANCE.xlsx'  # Default Excel file in the root directory

# Progress tracking variables
progress = {
    'current_stage': 'idle',
    'percent': 0,
    'message': 'Ready to process',
    'current_frame': 0,
    'total_frames': 0,
    'detected_frames': 0,
    'home_players': [],
    'away_players': [],
    'videos': {}  # Store progress for each video by ID
}

# Define team name aliases
TEAM_ALIASES = {
    "MAN UTD": "MANCHESTER UNITED",
    "MANU": "MANCHESTER UNITED", 
    "MUFC": "MANCHESTER UNITED",
    "MAN CITY": "MANCHESTER CITY",
    "MCFC": "MANCHESTER CITY",
    "LFC": "LIVERPOOL",
    "CFC": "CHELSEA",
    "AFC": "ARSENAL",
    "THFC": "TOTTENHAM",
    "SPURS": "TOTTENHAM"
}

# Initialize Flask application
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['FRAMES_FOLDER'] = FRAMES_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max upload
app.secret_key = 'player_extraction_app_key'

# Ensure upload and frames directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['FRAMES_FOLDER'], exist_ok=True)
os.makedirs('static/temp', exist_ok=True)

# Global variables
reader = None  # Global reader to reuse across videos
default_match_day = "MD1"

# Excel locations (based on user settings)
PLAYER_NAME_COL = 1  # Column A
MD1_COL = 5  # Column E
MD2_COL = 6  # Column F
MD3_COL = 7  # Column G
MD4_COL = 8  # Column H
MD5_COL = 9  # Column I
PLAYER_NAME_ROW_START = 2  # Row 2 is the header row
ADDITIONAL_PLAYERS_ROW = 60  # Row 60 for unmatched players

# Video Queue class for batch processing
class VideoQueue:
    def __init__(self):
        self.videos = []
        self.current_index = 0
        self.results = {}
        self.max_parallel = 4  # Maximum number of videos to process in parallel
        
    def add_video(self, video_path, excel_path, home_team=None, away_team=None, match_day=None):
        # Create a unique ID for this video
        video_id = str(uuid.uuid4())
        
        # Get filename
        filename = os.path.basename(video_path)
        
        self.videos.append({
            'id': video_id,
            'path': video_path,
            'filename': filename,
            'excel': excel_path,
            'home_team': home_team,
            'away_team': away_team,
            'match_day': match_day,
            'status': 'pending',
            'added_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'processed_at': None,
            'error': None
        })
        
        return video_id
    
    def get_video(self, video_id):
        """Get video details by ID"""
        for video in self.videos:
            if video['id'] == video_id:
                return video
        return None
    
    def remove_video(self, video_id):
        """Remove a video from the queue"""
        self.videos = [v for v in self.videos if v['id'] != video_id]
        if video_id in self.results:
            del self.results[video_id]
    
    def clear_completed(self):
        """Clear all completed videos from the queue"""
        completed_ids = [v['id'] for v in self.videos if v['status'] == 'completed']
        self.videos = [v for v in self.videos if v['status'] != 'completed']
        for vid_id in completed_ids:
            if vid_id in self.results:
                del self.results[vid_id]
    
    def get_next_pending(self):
        """Get the next pending video"""
        for video in self.videos:
            if video['status'] == 'pending':
                return video
        return None
    
    def count_processing(self):
        """Count the number of videos currently processing"""
        return sum(1 for v in self.videos if v['status'] == 'processing')
    
    def can_process_more(self):
        """Check if more videos can be processed in parallel"""
        return self.count_processing() < self.max_parallel
    
    def start_processing(self, video_id):
        """Mark a video as processing"""
        for video in self.videos:
            if video['id'] == video_id:
                video['status'] = 'processing'
                return True
        return False
    
    def complete_processing(self, video_id, results=None, error=None):
        """Mark a video as completed or error"""
        for video in self.videos:
            if video['id'] == video_id:
                if error:
                    video['status'] = 'error'
                    video['error'] = error
                else:
                    video['status'] = 'completed'
                    video['processed_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    if results:
                        self.results[video_id] = results
                return True
        return False
    
    def get_status(self):
        """Get status summary of all videos"""
        total = len(self.videos)
        completed = sum(1 for v in self.videos if v['status'] == 'completed')
        processing = sum(1 for v in self.videos if v['status'] == 'processing')
        error = sum(1 for v in self.videos if v['status'] == 'error')
        pending = sum(1 for v in self.videos if v['status'] == 'pending')
        
        return {
            'total': total,
            'completed': completed,
            'processing': processing,
            'pending': pending,
            'error': error,
            'is_processing': processing > 0
        }

# Initialize video queue
video_queue = VideoQueue()

# Helper function to get teams from Supabase
def get_teams_from_excel(excel_path=DEFAULT_EXCEL_PATH):
    """
    Get team names from Supabase database (replaces Excel file reading)
    The function name is kept the same for compatibility with existing code
    """
    teams = []
    try:
        # Get teams from Supabase
        team_data = get_teams()
        
        # Extract team names
        for team in team_data:
            teams.append(team["name"])
            print(f"Added team from Supabase: {team['name']}")
        
        print(f"Final teams list from Supabase: {teams}")
    except Exception as e:
        print(f"Error retrieving teams from Supabase: {e}")
        import traceback
        traceback.print_exc()
    
    return teams

def get_best_team_match(detected_team, excel_teams, threshold=75):
    """
    Find the best matching team from Supabase teams using fuzzy matching
    Returns the best match if score > threshold, otherwise None
    """
    if not detected_team or not excel_teams:
        return None
    
    # Check if detected team is in alias dictionary
    if detected_team.upper() in TEAM_ALIASES:
        canonical_name = TEAM_ALIASES[detected_team.upper()]
        # Check if canonical name exists in excel teams
        if canonical_name in excel_teams:
            print(f"Matched alias '{detected_team}' to '{canonical_name}'")
            return canonical_name
    
    # Try to fetch team by exact name first
    try:
        team = get_team_by_name(detected_team.upper())
        if team:
            print(f"Exact match found for '{detected_team}' in database")
            return team["name"]
    except Exception as e:
        print(f"Error searching team by exact name: {e}")
    
    # If exact match fails, use fuzzy matching
    # Get the best match and its score using fuzzy matching
    best_match, score = process.extractOne(detected_team.upper(), excel_teams)
    
    # Return the match if it's above the threshold
    if score >= threshold:
        print(f"Fuzzy matched '{detected_team}' to '{best_match}' with score {score}")
        return best_match
    
    print(f"No good match found for '{detected_team}'. Best match '{best_match}' with score {score}")
    return None

# Initialize OCR reader
def initialize_ocr():
    global reader
    if reader is None:
        print("Initializing OCR reader...")
        reader = easyocr.Reader(['en'])
    return reader

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Extract team names from video filename
def extract_teams_from_filename(video_path, excel_teams=None):
    """
    Extract team names from a pattern like "NEWCASTLE UNITED VS BORUSSIA DORTMUND MD1.mp4"
    Home team is before VS, away team is after VS and before MD
    If excel_teams is provided, tries to match detected teams to excel sheet names
    """
    filename = os.path.basename(video_path).upper()
    
    # Look for the pattern: HOME TEAM VS AWAY TEAM MD#
    match = re.search(r'(.+?)\s+VS\s+(.+?)(?:\s+MD\d+|\.\w+$)', filename)
    
    if match:
        home_team_raw = match.group(1).strip()
        away_team_raw = match.group(2).strip()
        
        print(f"Extracted from filename - Home: '{home_team_raw}', Away: '{away_team_raw}'")
        
        if excel_teams:
            # Try to match with excel teams
            home_team = get_best_team_match(home_team_raw, excel_teams) or home_team_raw
            away_team = get_best_team_match(away_team_raw, excel_teams) or away_team_raw
        else:
            home_team = home_team_raw
            away_team = away_team_raw
            
        print(f"Detected teams from filename: {home_team} vs {away_team}")
        return home_team, away_team
    
    # If pattern doesn't match, use placeholder names
    print(f"Could not extract teams from filename: {filename}")
    home_team = "HOME TEAM"
    away_team = "AWAY TEAM"
    return home_team, away_team

# Extract match day from filename
def extract_match_day_from_filename(video_path):
    """
    Extract match day from filename pattern like "NEWCASTLE UNITED VS BORUSSIA DORTMUND MD1.mp4"
    Returns the match day in format "MD#" or default_match_day if not found
    """
    filename = os.path.basename(video_path).upper()
    
    # Look for MD followed by numbers
    md_match = re.search(r'MD(\d+)', filename)
    if md_match:
        md_number = md_match.group(1)
        match_day = f"MD{md_number}"
        print(f"Extracted match day from filename: {match_day}")
        return match_day
    
    print(f"Could not extract match day from filename: {filename}, using default: {default_match_day}")
    return default_match_day

# Function to update progress
def update_progress(stage, percent, message='', video_id=None, **kwargs):
    """
    Update the progress tracking dictionary
    If video_id is provided, update progress for that specific video
    """
    global progress
    
    # Update main progress for backwards compatibility
    progress['current_stage'] = stage
    progress['percent'] = percent
    progress['message'] = message
    
    # Update any additional provided keys in the main progress
    for key, value in kwargs.items():
        progress[key] = value
    
    # If video_id is provided, update that specific video's progress
    if video_id:
        # Initialize video progress dictionary if it doesn't exist
        if video_id not in progress['videos']:
            progress['videos'][video_id] = {
                'current_stage': 'initializing',
                'percent': 0,
                'message': 'Starting processing',
                'current_frame': 0,
                'total_frames': 0,
                'detected_frames': 0,
                'home_players': [],
                'away_players': []
            }
        
        # Update video-specific progress
        progress['videos'][video_id]['current_stage'] = stage
        progress['videos'][video_id]['percent'] = percent
        progress['videos'][video_id]['message'] = message
        
        # Update any additional provided keys for this video
        for key, value in kwargs.items():
            progress['videos'][video_id][key] = value
    
    print(f"Progress update: {stage} - {percent}% - {message}")

# Extract frames from the video
def extract_frames(video_path, output_dir, video_id=None):
    print(f"Extracting frames from {video_path}...")
    update_progress('extracting', 0, 'Starting frame extraction', video_id=video_id)
    
    # Create a unique ID for this extraction session to avoid path conflicts in Cloudinary
    extraction_id = str(uuid.uuid4())[:8]
    cloud_output_dir = f"{output_dir}/{extraction_id}"
    
    # If video is a Cloudinary URL, download temporarily
    temp_video_path = None
    if video_path.startswith('http'):
        temp_video = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
        temp_video_path = temp_video.name
        temp_video.close()
        cloudinary_download(video_path, temp_video_path)
        video_path = temp_video_path
    
    # Open the video
    cap = cv2.VideoCapture(video_path)
    
    if not cap.isOpened():
        print("Error: Could not open video.")
        update_progress('error', 100, 'Could not open video file', video_id=video_id)
        # Clean up if we downloaded a temp file
        if temp_video_path and os.path.exists(temp_video_path):
            os.unlink(temp_video_path)
        return []
    
    # Get video properties
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps
    
    print(f"Video duration: {duration:.2f} seconds, FPS: {fps}, Total frames: {total_frames}")
    update_progress('extracting', 5, f'Video duration: {duration:.2f}s, FPS: {fps}', total_frames=total_frames, video_id=video_id)
    
    # Increase frame capture rate to ensure we don't miss any player rating screens
    # For short videos, extract frames much more frequently
    if duration < 30:
        frame_interval = max(1, int(fps / 6))  # Capture 6 frames per second
    elif duration < 120:
        frame_interval = max(1, int(fps / 4))  # Capture 4 frames per second
    else:
        frame_interval = max(1, int(fps / 3))  # Capture 3 frames per second
    
    print(f"Using frame interval of {frame_interval} (approximately {fps/frame_interval:.1f} frames per second)")
    
    frame_count = 0
    saved_frames = []
    
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            if frame_count % frame_interval == 0:
                # Create frame filename
                frame_filename = f"frame_{frame_count}.jpg"
                frame_path = f"{cloud_output_dir}/{frame_filename}"
                
                # Upload frame to Cloudinary
                cloud_url = save_cv2_image(frame, frame_path)
                saved_frames.append(cloud_url)
                
                # Update progress
                if total_frames > 0:
                    progress_percent = min(95, 5 + (frame_count / total_frames * 90))
                    update_progress('extracting', progress_percent, 
                                   f'Extracted {len(saved_frames)} frames ({frame_count}/{total_frames})',
                                   current_frame=frame_count, video_id=video_id)
                
                # Print progress
                if len(saved_frames) % 10 == 0:
                    print(f"Extracted {len(saved_frames)} frames...")
            
            frame_count += 1
    finally:
        cap.release()
        # Clean up if we downloaded a temp file
        if temp_video_path and os.path.exists(temp_video_path):
            os.unlink(temp_video_path)
    
    print(f"Total frames extracted: {len(saved_frames)}")
    update_progress('extracting', 100, f'Finished extracting {len(saved_frames)} frames', video_id=video_id)
    return saved_frames

# Extract text from image using OCR
def extract_text_from_image(image_path, reader):
    # Get the image - handle both local paths and Cloudinary URLs
    if image_path.startswith('http'):
        # For Cloudinary URLs, use our helper to get the image data
        image = get_image_as_array(image_path)
        if image is None:
            print(f"Error loading image from URL: {image_path}")
            return []
    else:
        # Read local image
        image = cv2.imread(image_path)
    
    # Get OCR results
    results = reader.readtext(image)
    
    # Return the detected text
    return results

# Process text to extract player information
def process_text_data(ocr_results):
    # Initialize player data containers
    home_players = []
    away_players = []
    current_section = None
    
    # Combine results into a single string
    text_blocks = []
    for detection in ocr_results:
        text = detection[1]
        confidence = detection[2]
        if confidence > 0.2:
            text_blocks.append(text.strip())
    
    # Join all detected text for section detection
    all_text = " ".join(text_blocks)
    
    # Determine if we're looking at home or away team ratings
    if "Player Ratings: Home" in all_text or "Player Ratings: Home" in " ".join(text_blocks):
        current_section = "home"
    elif "Player Ratings: Away" in all_text or "Player Ratings: Away" in " ".join(text_blocks):
        current_section = "away"
    
    # Known false positives to exclude (expanded list)
    false_positives = [
        # Button and UI elements
        "ack maia", "back", "pack", "sack", "ack", "acc", "maia", "main", "main menu", 
        "page", "click", "next", "prev", "menu", "rank", "rankings", "overall", "squad",
        "default", "formation", "tactics", "attacking", "balanced", "defensive", 
        # Stats and numbers
        "irwf", "0 w", "0w", "*7.5", "43%", "6.u", "6u", "7.0", "9.0", "8.5", "10.0",
        "percent", "rating", "ratings", "score", "min", "max", "average", "avg",
        # Game UI elements
        "press", "press any", "continue", "exit", "return", "pause", "resume", "start", "options",
        "settings", "audio", "video", "controls", "select", "cancel", "confirm", "home", "away", "awav",
        # Positions that might be misread as names
        "gk", "rwb", "lwb", "cb", "rb", "lb", "cdm", "cm", "cam", "rm", "lm", "rw", "lw", "st", "cf",
        # Match stats terms
        "possession", "shots", "shots on target", "passes", "pass accuracy", "tackles", "fouls",
        # Additional unwanted terms from the user's query
        "dmfi", "dmf", "kui", "kul", "horiano", "huriano"
    ]
    
    # Extract player names
    if current_section:
        # First, try to find full names (multi-word entries)
        for i, text in enumerate(text_blocks):
            # Skip ratings values, percentages, and short tokens
            if (re.match(r'^[\d.]+$', text) or  # Pure numbers like 6.5
                re.match(r'^\d+%$', text) or    # Percentage values like 43%
                re.match(r'^[*]?\d+\.\d+$', text) or  # Rated values like *7.5
                re.match(r'^\d+\.[A-Za-z]$', text) or  # Special ratings like 6.U
                len(text) < 3):                 # Very short tokens
                continue
                
            # Skip position indicators and known UI elements
            if (re.match(r'^[A-Z]{2,3}$', text) or  # Position codes like GK, CB
                text.upper() in [fp.upper() for fp in false_positives] or  # Known false positives
                "Player Ratings" in text or     # UI header text
                "Back" in text or               # Navigation elements
                "Away" == text or "Home" == text or
                "Awav" == text):  # Common misread of "Away"
                continue
            
            # Check if text is just numbers and simple symbols
            if re.match(r'^[0-9.+\-*/]+$', text):
                continue
                
            # Additional filtering for common OCR misreads
            if (re.match(r'^[0-9\s]+$', text) or  # Just numbers and spaces
                len(normalize_player_name(text)) <= 1 or  # Too short after normalization
                not re.search(r'[AEIOU]', text.upper())):  # No vowels (likely not a real name)
                continue
            
            # Clean up the text
            clean_name = text.strip()
            
            # Apply name correction
            corrected_name = correct_player_name(clean_name)
            
            # Add to appropriate list if not a duplicate
            if current_section == "home" and corrected_name not in home_players:
                home_players.append(corrected_name)
            elif current_section == "away" and corrected_name not in away_players:
                away_players.append(corrected_name)
    
    return home_players, away_players

# Normalize player name to handle special characters and variations
def normalize_player_name(name):
    if not name:
        return ""
        
    # Convert to string and uppercase for consistency
    name = str(name).upper()
    
    # Remove excess whitespace
    name = " ".join(name.split())
    
    # Replace common special characters
    replacements = {
        "Ü": "U", "Ö": "O", "Ä": "A",
        "É": "E", "È": "E", "Ê": "E", "Ë": "E",
        "Á": "A", "À": "A", "Â": "A", "Ã": "A",
        "Í": "I", "Ì": "I", "Î": "I", "Ï": "I",
        "Ó": "O", "Ò": "O", "Ô": "O", "Õ": "O",
        "Ú": "U", "Ù": "U", "Û": "U",
        "Ñ": "N", "Ç": "C", "Š": "S", "Ž": "Z",
        "ß": "SS", "Æ": "AE", "Ø": "O"
    }
    
    for orig, repl in replacements.items():
        name = name.replace(orig, repl)
    
    # Remove common prefixes that might be misread
    prefixes_to_remove = ["MR ", "MR. ", "DR ", "DR. "]
    for prefix in prefixes_to_remove:
        if name.startswith(prefix):
            name = name[len(prefix):]
    
    # Remove non-alphabetic characters except spaces
    name = re.sub(r'[^A-Z ]', '', name)
    
    # Fix common OCR errors
    ocr_fixes = {
        "0": "O", "1": "I", "5": "S", "8": "B",
        "VV": "W", "RN": "M", "CL": "CI", "II": "H",
        "NNN": "NN", "NNM": "NM", "MN": "M N"
    }
    
    for orig, repl in ocr_fixes.items():
        name = name.replace(orig, repl)
    
    return name.strip()

# Update the KNOWN_OCR_CORRECTIONS dictionary with more variations
KNOWN_OCR_CORRECTIONS = {
    # Other player names
    "KULUSEVSKI": "D KULUSEVSKI",
    "KULUSEVSLD": "D KULUSEVSKI",
    "KULUSEVSK1": "D KULUSEVSKI",
    "DEJAN KULUSEVSKI": "D KULUSEVSKI"
}

# Update the correct_player_name function to better handle these specific misreadings
def correct_player_name(name):
    """
    Apply corrections for known player OCR misreads
    """
    if not name:
        return name
        
    # Normalize and uppercase the name
    norm_name = normalize_player_name(name)
    
    # Check for exact match in corrections dictionary
    if norm_name in KNOWN_OCR_CORRECTIONS:
        return KNOWN_OCR_CORRECTIONS[norm_name]
    
    # Check for partial matches (substring)
    for known_wrong, correction in KNOWN_OCR_CORRECTIONS.items():
        # If the known wrong name is a substantial part of the detected name
        if (known_wrong in norm_name and len(known_wrong) >= 5):
            return correction
            
        # If the detected name is a substantial part of a known wrong name
        if (norm_name in known_wrong and len(norm_name) >= 5):
            return correction
    
    # Try checking for last name matches
    name_parts = norm_name.split()
    if len(name_parts) > 0:
        last_name = name_parts[-1]
        for known_wrong, correction in KNOWN_OCR_CORRECTIONS.items():
            known_parts = known_wrong.split()
            if len(known_parts) > 0 and known_parts[-1] == last_name:
                return correction
    
    return name

# Add a function for preprocessing high-confidence name corrections
def preprocess_detected_names(names):
    """
    Apply preprocessing to detected player names before further processing
    Handles special cases of commonly misread names
    """
    processed_names = []
    
    for name in names:
            # Apply regular correction
            corrected = correct_player_name(name)
            processed_names.append(corrected)
    
    # Remove duplicates while preserving order
    return list(dict.fromkeys(processed_names))

# Function to check if two names are referring to the same player
def are_similar_names(name1, name2, threshold=80):
    """
    Check if two player names are similar using various techniques
    Returns True if names are considered similar, False otherwise
    
    Parameters:
    name1 - First player name
    name2 - Second player name
    threshold - Similarity threshold (0-100) for fuzzy matching
    """
    # Convert to comparable format
    norm1 = normalize_player_name(name1)
    norm2 = normalize_player_name(name2)
    
    # Skip empty names
    if not norm1 or not norm2:
        return False
    
    # Direct match
    if norm1 == norm2:
        return True
    
    # Simple partial match - one is contained within the other
    if (len(norm1) >= 3 and norm1 in norm2) or (len(norm2) >= 3 and norm2 in norm1):
        return True
    
    # Check if last names match (if multiple words)
    parts1 = norm1.split()
    parts2 = norm2.split()
    
    if len(parts1) > 1 and len(parts2) > 1:
        if parts1[-1] == parts2[-1]:  # Last names match
            # Check if first initials match
            if parts1[0][0] == parts2[0][0]:
                return True
    
    # Use Levenshtein distance for more advanced fuzzy matching
    from fuzzywuzzy import fuzz
    ratio = fuzz.ratio(norm1, norm2)
    if ratio >= threshold:
        return True
        
    # Check token set ratio (handles word reordering and partial matches better)
    token_ratio = fuzz.token_set_ratio(norm1, norm2)
    if token_ratio >= threshold:
        return True
        
    return False

# Function to merge similar player names, keeping the most complete versions
def merge_similar_names(player_names):
    """
    Merge similar player names to reduce duplicates and keep the most complete versions
    
    Parameters:
    player_names - List of player names to merge
    
    Returns:
    List of merged unique player names
    """
    if not player_names:
        return []
    
    # Apply specific corrections first
    corrected_names = [correct_player_name(name) for name in player_names]
    
    # Initial normalization of all names
    normalized_names = [(name, normalize_player_name(name)) for name in corrected_names]
    
    # Filter out very short or empty names (likely OCR errors)
    normalized_names = [(orig, norm) for orig, norm in normalized_names if len(norm) >= 2]
    
    # Sort by length (longer names first - tend to be more complete) and then alphabetically for deterministic results
    sorted_names = sorted(normalized_names, key=lambda x: (-len(x[1]), x[1]))
    
    merged = []
    merged_originals = []
    
    for orig_name, norm_name in sorted_names:
        # Skip if this name is already covered by an existing entry
        if any(are_similar_names(orig_name, existing, threshold=75) for existing in merged_originals):
            continue
        
        merged.append(norm_name)
        merged_originals.append(orig_name)
    
    # Return the original form of the merged names (not normalized) for better display
    return merged_originals

# Get parts of a player name (first, middle, last)
def get_name_parts(name):
    if not name:
        return [], ""
        
    name_str = str(name).strip().upper()
    parts = name_str.split()
    
    # Handle case with no parts
    if not parts:
        return [], ""
    
    # Handle single-part names
    if len(parts) == 1:
        return [], parts[0]
    
    # For multi-part names
    last_name = parts[-1]
    first_parts = parts[:-1]
    
    return first_parts, last_name

# Function to specifically match player names for Excel comparison
def names_match(excel_name, extracted_name, threshold=75):
    """
    Check if an extracted player name matches an Excel/database name
    Returns True if names are considered a match, False otherwise
    
    Parameters:
    excel_name - Name from Excel/database (source of truth)
    extracted_name - Name extracted from OCR
    threshold - Similarity threshold (0-100) for fuzzy matching
    """
    # Skip empty names
    if not excel_name or not extracted_name:
        return False
    
    # Normalize both names to handle special characters
    norm_excel = normalize_player_name(excel_name)
    norm_extracted = normalize_player_name(extracted_name)
    
    # Direct match
    if norm_excel == norm_extracted:
        return True
    
    # One is contained within the other (for partial matches)
    if len(norm_excel) >= 3 and norm_excel in norm_extracted:
        return True
    if len(norm_extracted) >= 3 and norm_extracted in norm_excel:
        return True
    
    # Extract name parts
    excel_parts = norm_excel.split()
    extracted_parts = norm_extracted.split()
    
    # Last name matches (if both have multiple parts)
    if len(excel_parts) > 1 and len(extracted_parts) > 1:
        excel_last = excel_parts[-1]
        extracted_last = extracted_parts[-1]
        
        if excel_last == extracted_last and len(excel_last) >= 3:
            return True
            
        # First initial + last name match
        if excel_parts[0][0] == extracted_parts[0][0] and excel_last == extracted_last:
            return True
    
    # Use more advanced fuzzy matching
    from fuzzywuzzy import fuzz
    
    # Use token sort ratio for names (handles word reordering)
    token_sort_ratio = fuzz.token_sort_ratio(norm_excel, norm_extracted)
    if token_sort_ratio >= threshold + 10:  # Higher threshold for token sort
        return True
    
    # Use token set ratio (handles partial matches better)
    token_set_ratio = fuzz.token_set_ratio(norm_excel, norm_extracted)
    if token_set_ratio >= threshold + 5:  # Higher threshold for token set
        return True
    
    # Use partial ratio for handling substrings
    partial_ratio = fuzz.partial_ratio(norm_excel, norm_extracted)
    if partial_ratio >= threshold + 15:  # Higher threshold for partial matching
        return True
    
    # Advanced: Check if the last name is contained in the other name
    # and first initials match - helps with OCR errors in last names
    if len(excel_parts) > 1 and len(extracted_parts) > 1:
        if excel_parts[0][0] == extracted_parts[0][0]:  # First initials match
            # Check if last name is contained in the other last name with a high similarity
            last_name_ratio = fuzz.ratio(excel_parts[-1], extracted_parts[-1])
            if last_name_ratio >= 85:  # High threshold for last name similarity
                return True
    
    return False

# Add this function after extract_text_from_image

def extract_player_cards(image_path, reader):
    """
    Extract player names from the rating cards that appear in frames
    Player ratings appear in dark rectangular boxes with player name and rating (like "Isco 7.0")
    Each frame can contain up to 3 player cards, each with dimensions of approximately 680x87 pixels
    
    Parameters:
    image_path - Path or URL to the image file
    reader - OCR reader instance
    
    Returns:
    List of extracted player names
    """
    # Read the image
    if image_path.startswith('http'):
        # For Cloudinary URLs, use our helper to get the image data
        image = get_image_as_array(image_path)
        if image is None:
            print(f"Failed to read image: {image_path}")
            return []
    else:
        # Read local image
        image = cv2.imread(image_path)
        if image is None:
            print(f"Failed to read image: {image_path}")
            return []
    
    # Get image dimensions
    height, width = image.shape[:2]
    
    # Create a folder in Cloudinary for player cards
    base_image_name = os.path.basename(image_path).replace('.jpg', '')
    if '/' in base_image_name:
        # For Cloudinary URLs, extract the filename without the path
        base_image_name = base_image_name.split('/')[-1]
    if '.' in base_image_name:
        # Remove any file extension
        base_image_name = os.path.splitext(base_image_name)[0]
    
    cards_dir = 'player_cards'
    
    # Create a debug image for visualization
    debug_img = image.copy()
    
    player_names = []
    card_count = 0
    
    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Use adaptive thresholding to handle different lighting conditions
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                   cv2.THRESH_BINARY_INV, 11, 2)
    
    # Define unwanted UI terms and labels to filter out
    unwanted_terms = [
        # Game UI labels
        'home', 'away', 'vs', 'player', 'rating', 'ratings', 'awav', 
        'team', 'pause', 'resume', 'exit', 'back', 
        # Short UI elements or misreads
        'dmfi', 'kul', 'kui', 'horiano', 'huriano', 'dmf', 'gk', 'df', 'mf', 'fw',
        # Button and UI elements (from false_positives)
        "ack maia", "back", "pack", "sack", "ack", "acc", "maia", "main", "main menu", 
        "page", "click", "next", "prev", "menu", "rank", "rankings", "overall", "squad",
        "default", "formation", "tactics", "attacking", "balanced", "defensive",
        # Position codes
        "gk", "rwb", "lwb", "cb", "rb", "lb", "cdm", "cm", "cam", "rm", "lm", "rw", "lw", "st", "cf"
    ]
    
    # Use morphological operations to eliminate noise
    kernel = np.ones((3, 3), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
    
    # Find contours
    contours, hierarchy = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # First, check if we are looking at a player ratings screen
    # Search for the "Player Ratings: Home" or "Player Ratings: Away" text at the top
    is_ratings_screen = False
    top_area = image[0:int(height * 0.15), 0:width]
    top_results = reader.readtext(top_area)
    for detection in top_results:
        text = detection[1]
        if "Player Ratings" in text:
            is_ratings_screen = True
            cv2.putText(debug_img, f"RATINGS SCREEN: {text}", (10, 30), 
                         cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            break
    
    if not is_ratings_screen:
        # If this doesn't look like a ratings screen, don't waste time with card detection
        debug_path = f"{cards_dir}/{base_image_name}_debug.jpg"
        # Save debug image to Cloudinary
        save_cv2_image(debug_img, debug_path)
        return []
    
    # Expected card height (87 pixels in original reference)
    expected_card_height_ratio = 87 / 424  # Original reference dimensions
    expected_card_height = int(height * expected_card_height_ratio)
    
    # Find rectangles that could be player cards
    min_width = int(width * 0.6)  # Player cards are at least 60% of the screen width
    min_height = int(expected_card_height * 0.7)
    max_height = int(expected_card_height * 1.3)
    
    # To handle overlapping player cards, store their y-coordinates
    card_y_positions = []
    
    # Sort contours by area, largest first
    sorted_contours = sorted(contours, key=cv2.contourArea, reverse=True)
    
    for contour in sorted_contours:
        x, y, w, h = cv2.boundingRect(contour)
        
        # Check if this could be a player card
        if (w > min_width and min_height <= h <= max_height):
            # Check if we already have a card at similar y position (within 20 pixels)
            is_duplicate = False
            for existing_y in card_y_positions:
                if abs(existing_y - y) < 20:
                    is_duplicate = True
                    break
            
            if is_duplicate:
                continue
            
            # Store this card's y position
            card_y_positions.append(y)
            
            # Draw rectangle around the card
            cv2.rectangle(debug_img, (x, y), (x+w, y+h), (0, 255, 0), 2)
            
            # Extract the card
            card_count += 1
            card = image[y:y+h, x:x+w]
            
            # Save the original card to Cloudinary
            card_filename = f"{base_image_name}_card_{card_count}.jpg"
            card_path = f"{cards_dir}/{card_filename}"
            card_url = save_cv2_image(card, card_path)
            
            # Add marker text to debug image
            cv2.putText(debug_img, f"Card {card_count} ({w}x{h})", (x, y-10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            
            # Preprocess the card for better OCR
            card_gray = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY)
            
            # Use both thresholding methods for better results
            _, card_binary = cv2.threshold(card_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            
            # Save the processed card image to Cloudinary
            processed_card_filename = f"{base_image_name}_card_{card_count}_processed.jpg"
            processed_card_path = f"{cards_dir}/{processed_card_filename}"
            processed_card_url = save_cv2_image(card_binary, processed_card_path)
            
            # Use OCR to extract the player name and rating
            try:
                # Try both original and processed versions
                original_results = reader.readtext(card)
                processed_results = reader.readtext(card_binary)
                
                # Combine results for more robustness
                card_results = original_results + processed_results
                
                player_name = None
                rating = None
                position = None
                
                # Find the player name and rating
                for detection in card_results:
                    text = detection[1].strip()
                    if not text:
                        continue
                    
                    # Check for rating (e.g., 7.5, 6.5, etc.)
                    if re.match(r'^[0-9]+\.[0-9]+$', text) or text in ["10.0", "10"]:
                        rating = text
                    # Check for position codes (usually 2-3 letters at the start of card)
                    elif re.match(r'^[A-Z]{2,3}$', text):
                        position = text
                    # Everything else could be a player name (if it's long enough)
                    elif len(text) > 3 and not text.isdigit():
                        if text.lower() not in unwanted_terms:
                            # If we already have a name, combine them or take the longer one
                            if player_name:
                                if len(text) > len(player_name):
                                    player_name = text
                            else:
                                player_name = text
                
                # If we found a player name, validate and add it
                if player_name:
                    normalized = normalize_player_name(player_name)
                    
                    # Skip names that are just 2-3 uppercase letters (likely positions)
                    if re.match(r'^[A-Z]{2,3}$', normalized):
                        continue
                    
                    # Skip names that are in the list of unwanted terms
                    if normalized.lower() in [term.lower() for term in unwanted_terms]:
                        continue
                    
                    # Apply corrections to known misreadings
                    corrected_name = correct_player_name(player_name)
                    
                    # Only add valid names with at least one vowel
                    if corrected_name and re.search(r'[AEIOU]', normalized) and corrected_name not in player_names:
                        player_names.append(corrected_name)
                        
                        # Add the card to our debug image in red to show it was successfully processed
                        cv2.rectangle(debug_img, (x, y), (x+w, y+h), (0, 0, 255), 2)
                        cv2.putText(debug_img, corrected_name, (x, y-10), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                        
                        # Save player card info in a JSON string
                        info_data = {
                            "detected_name": player_name,
                            "normalized": normalized,
                            "corrected": corrected_name,
                            "rating": rating or "Unknown",
                            "position": position or "Unknown"
                        }
                        # We don't need to save the text file, but could upload the JSON to Cloudinary if needed
            
            except Exception as e:
                print(f"Error processing card {card_count}: {e}")
    
    # Add information about how many cards were detected
    cv2.putText(debug_img, f"Found {card_count} cards, {len(player_names)} names", 
                (10, height - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
    
    # Save the debug image to Cloudinary
    debug_path = f"{cards_dir}/{base_image_name}_debug.jpg"
    save_cv2_image(debug_img, debug_path)
    
    return player_names

# Update identify_player_ratings_frames to use the new preprocessing
def identify_player_ratings_frames(frames, reader, video_id=None):
    """
    Analyze frames to find player ratings screens and extract player names
    Uses both general text extraction and targeted player card detection
    
    Parameters:
    frames - List of frame file paths to analyze
    reader - OCR reader instance
    video_id - Optional video ID for progress tracking
    
    Returns:
    Tuple of (home_players, away_players) lists
    """
    print("Analyzing frames to find player ratings screens...")
    update_progress('analyzing', 0, 'Starting frame analysis to find player ratings', video_id=video_id)
    
    home_players = []
    away_players = []
    detected_frames = 0
    
    # Track frames where we found player ratings
    home_rating_frames = []
    away_rating_frames = []
    
    # First pass: identify player rating frames
    for i, frame_path in enumerate(frames):
        # Update progress
        progress_percent = (i / len(frames)) * 60  # First pass uses 60% of progress
        update_progress('analyzing', progress_percent, 
                       f'Scanning frame {i+1}/{len(frames)}: {os.path.basename(frame_path)}',
                       video_id=video_id)
        
        # Extract text from the frame with low detail (faster)
        ocr_results = reader.readtext(frame_path, detail=1, paragraph=False)
        
        # Check if this frame contains player ratings
        contains_home = False
        contains_away = False
        
        text_blocks = [detection[1] for detection in ocr_results]
        combined_text = " ".join(text_blocks)
        
        if "Player Ratings: Home" in combined_text or any("Player Ratings: Home" in text for text in text_blocks):
            contains_home = True
            home_rating_frames.append(frame_path)
            detected_frames += 1
        
        if "Player Ratings: Away" in combined_text or any("Player Ratings: Away" in text for text in text_blocks):
            contains_away = True
            away_rating_frames.append(frame_path)
            detected_frames += 1
    
    # Second pass: detailed OCR only on player rating frames
    # Process home rating frames
    for i, frame_path in enumerate(home_rating_frames):
        progress_percent = 60 + (i / len(home_rating_frames + away_rating_frames) * 35)
        update_progress('analyzing', progress_percent, 
                      f'Processing HOME player ratings in frame {os.path.basename(frame_path)}',
                      detected_frames=detected_frames,
                      video_id=video_id)
        
        # Try to extract player names from cards first (more accurate)
        player_cards = extract_player_cards(frame_path, reader)
        if player_cards:
            # Apply preprocessing for commonly misread names
            home_players.extend(player_cards)
            update_progress('analyzing', progress_percent, 
                          f'Extracted {len(player_cards)} home players from cards in frame',
                          home_players=home_players,
                          video_id=video_id)
        else:
            # Fall back to regular OCR if no cards were detected
            ocr_results = extract_text_from_image(frame_path, reader)
            h_players, _ = process_text_data(ocr_results)
            home_players.extend(h_players)
            update_progress('analyzing', progress_percent, 
                          f'Extracted {len(h_players)} home players from text in frame',
                          home_players=home_players,
                          video_id=video_id)
    
    # Process away rating frames
    for i, frame_path in enumerate(away_rating_frames):
        progress_percent = 60 + ((len(home_rating_frames) + i) / len(home_rating_frames + away_rating_frames) * 35)
        update_progress('analyzing', progress_percent, 
                      f'Processing AWAY player ratings in frame {os.path.basename(frame_path)}',
                      detected_frames=detected_frames,
                      video_id=video_id)
        
        # Try to extract player names from cards first (more accurate)
        player_cards = extract_player_cards(frame_path, reader)
        if player_cards:
            away_players.extend(player_cards)
            update_progress('analyzing', progress_percent, 
                          f'Extracted {len(player_cards)} away players from cards in frame',
                          away_players=away_players,
                          video_id=video_id)
        else:
            # Fall back to regular OCR if no cards were detected
            ocr_results = extract_text_from_image(frame_path, reader)
            _, a_players = process_text_data(ocr_results)
            away_players.extend(a_players)
            update_progress('analyzing', progress_percent, 
                          f'Extracted {len(a_players)} away players from text in frame',
                          away_players=away_players,
                          video_id=video_id)
    
    # Clean and merge similar names
    update_progress('analyzing', 95, 'Merging similar player names', video_id=video_id)
    
    # Apply preprocessing to handle commonly misread names before merging
    home_players = preprocess_detected_names(home_players)
    away_players = preprocess_detected_names(away_players)
    
    # Then apply standard merging
    cleaned_home_players = merge_similar_names(home_players)
    cleaned_away_players = merge_similar_names(away_players)
    
    print(f"Extracted {len(cleaned_home_players)} home players and {len(cleaned_away_players)} away players")
    update_progress('analyzing', 100, 
                  f'Finished analysis: {len(cleaned_home_players)} home players, {len(cleaned_away_players)} away players',
                  home_players=cleaned_home_players,
                  away_players=cleaned_away_players,
                  video_id=video_id)
    
    return cleaned_home_players, cleaned_away_players

# Create a function to prepare the data for web display
def prepare_player_data_for_display(home_team, away_team, home_players, away_players, excel_path=None):
    """
    Prepare player data for web display using Supabase database
    Returns dictionaries of home and away team players with their status
    """
    home_data = {}
    away_data = {}
    unmatched_home = []
    unmatched_away = []
    
    try:
        # Get home team ID
        home_team_data = get_team_by_name(home_team)
        if home_team_data:
            home_team_id = home_team_data["id"]
            
            # Get all players for home team
            home_team_players = get_players_by_team(home_team_id)
            
            # Mark all existing players as 0 (not in video)
            for player in home_team_players:
                if player["name"]:
                    home_data[player["name"]] = 0
            
            # Mark players found in video as 1
            for extracted_player in home_players:
                matched = False
                for db_player in home_team_players:
                    if names_match(db_player["name"], extracted_player):
                        home_data[db_player["name"]] = 1
                        matched = True
                        break
                
                if not matched:
                    # Filter out known problematic players that are commonly misidentified
                    if not is_known_misidentified_player(extracted_player):
                        unmatched_home.append(extracted_player)
        else:
            # If no team found, filter and add extracted players as unmatched
            unmatched_home = [p for p in home_players if not is_known_misidentified_player(p)]
                
        # Get away team ID
        away_team_data = get_team_by_name(away_team)
        if away_team_data:
            away_team_id = away_team_data["id"]
            
            # Get all players for away team
            away_team_players = get_players_by_team(away_team_id)
            
            # Mark all existing players as 0 (not in video)
            for player in away_team_players:
                if player["name"]:
                    away_data[player["name"]] = 0
            
            # Mark players found in video as 1
            for extracted_player in away_players:
                matched = False
                for db_player in away_team_players:
                    if names_match(db_player["name"], extracted_player):
                        away_data[db_player["name"]] = 1
                        matched = True
                        break
                
                if not matched:
                    # Filter out known problematic players that are commonly misidentified
                    if not is_known_misidentified_player(extracted_player):
                        unmatched_away.append(extracted_player)
        else:
            # If no team found, filter and add extracted players as unmatched
            unmatched_away = [p for p in away_players if not is_known_misidentified_player(p)]
            
    except Exception as e:
        print(f"Error preparing player data from Supabase: {str(e)}")
        traceback.print_exc()
        # If database processing fails, filter and use extracted players as unmatched
        unmatched_home = [p for p in home_players if not is_known_misidentified_player(p)]
        unmatched_away = [p for p in away_players if not is_known_misidentified_player(p)]
    
    return home_data, away_data, unmatched_home, unmatched_away

# Add a helper function to identify commonly misidentified players
def is_known_misidentified_player(player_name):
    """
    Check if a player name matches a known problematic player that is commonly misidentified
    Returns True if the player is a known misidentified player, False otherwise
    """
    if not player_name:
        return False
        
    # Function now returns False for all inputs since we've removed all known misidentified players
    return False

def update_excel_with_new_players(excel_path, team_name, new_players, match_day_column, positions=None):
    """
    Update Supabase with newly detected players that don't exist in the team
    Returns number of players added
    """
    if not team_name or not new_players:
        return 0
    
    positions = positions or {}  # Default to empty dict if None
    
    try:
        # Get team ID
        team_data = get_team_by_name(team_name)
        if not team_data:
            print(f"Team {team_name} not found in Supabase")
            return 0
        
        team_id = team_data["id"]
        
        # Get existing players for this team
        team_players = get_players_by_team(team_id)
        existing_players = [p["name"].strip().upper() for p in team_players if p["name"]]
        
        # Add new players if they don't exist in the database
        added_count = 0
        for player in new_players:
            # Skip if player already exists (using fuzzy matching)
            if any(names_match(player, existing) for existing in existing_players):
                continue
                
            # Skip known misidentified players like Hjulmand variations
            if is_known_misidentified_player(player):
                continue
            
            # Get position for this player (default to Unknown)
            position = positions.get(player, "Unknown")
            
            # Add new player to database
            result = add_new_player(player, team_id, position, "Active")
            if result:
                added_count += 1
                
                # Extract match day number from column
                md_number = 1  # Default
                if isinstance(match_day_column, int) and MD1_COL <= match_day_column <= MD5_COL:
                    md_number = match_day_column - MD1_COL + 1
                
                match_day_name = f"MD{md_number}"
                
                # Add appearance record for this match day
                update_player_appearance(result["id"], match_day_name, True)
                
                print(f"Added new player '{player}' ({position}) to team {team_name}, with appearance for {match_day_name}")
        
        print(f"Added {added_count} new players to {team_name} in Supabase")
        return added_count
    
    except Exception as e:
        print(f"Error updating Supabase with new players: {str(e)}")
        traceback.print_exc()
        return 0

def get_match_day_column(match_day_value):
    """
    Get the column index for the specified match day
    """
    if not match_day_value or not isinstance(match_day_value, str):
        return MD1_COL
    
    match_day_value = match_day_value.upper()
    if match_day_value == "MD1":
        return MD1_COL
    elif match_day_value == "MD2":
        return MD2_COL
    elif match_day_value == "MD3":
        return MD3_COL
    elif match_day_value == "MD4":
        return MD4_COL
    elif match_day_value == "MD5":
        return MD5_COL
    else:
        # Try to extract number from MDX format
        match = re.search(r'MD(\d+)', match_day_value)
        if match:
            md_num = int(match.group(1))
            if 1 <= md_num <= 5:
                return MD1_COL + md_num - 1
    
    # Default to MD1
    return MD1_COL

# Function to check if a match already exists
def match_exists(home_team, away_team, match_day):
    """
    Check if a match with the same home team, away team, and match day already exists
    Returns the match ID if it exists, otherwise None
    """
    try:
        # Get Supabase client
        supabase = get_supabase_client()
        
        # Get home and away team IDs
        home_team_data = get_team_by_name(home_team)
        away_team_data = get_team_by_name(away_team)
        
        if not home_team_data or not away_team_data:
            return None
            
        home_team_id = home_team_data["id"]
        away_team_id = away_team_data["id"]
        
        # Check if match exists
        match_data = supabase.table("matches").select("id") \
            .eq("home_team_id", home_team_id) \
            .eq("away_team_id", away_team_id) \
            .eq("match_day", match_day) \
            .execute()
            
        if match_data.data:
            return match_data.data[0]["id"]
        
        return None
    except Exception as e:
        print(f"Error checking if match exists: {str(e)}")
        return None

@app.route('/')
@app.route('/home')
def index():
    # Get team names from Excel for the dropdown
    teams = get_teams_from_excel()
    print(f"Found {len(teams)} teams in Excel: {teams}")
    
    # Debug check of team names
    if not teams:
        print("WARNING: No teams found in Excel file!")
    else:
        print("Teams to be displayed in dropdown:")
        for team in teams:
            print(f"  - {team}")
    
    return render_template('home.html', teams=teams)

@app.route('/upload', methods=['POST'])
def upload_file():
    # Check if a file was uploaded
    if 'file' not in request.files:
        flash('No file part')
        return redirect(request.url)
    
    file = request.files['file']
    
    # If no file was selected
    if file.filename == '':
        flash('No selected file')
        return redirect(request.url)
    
    # If the file is allowed
    if file and allowed_file(file.filename):
        # Clean up previous uploads and frames
        # We don't need to clean up Cloudinary files - they'll be overwritten
        
        # Secure filename and save temporarily
        filename = secure_filename(file.filename)
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1])
        temp_file_path = temp_file.name
        temp_file.close()
        file.save(temp_file_path)
        
        try:
            # Upload to Cloudinary
            file_path = f"uploads/{filename}"
            cloud_url = cloudinary_upload(file_path, temp_file_path)
            
            # Store the Cloudinary URL in session for processing
            session['video_path'] = cloud_url
            
            # Handle Excel file selection
            use_default_excel = request.form.get('use_default_excel', '1') == '1'
            
            if use_default_excel:
                # Check if default Excel exists
                if os.path.exists(DEFAULT_EXCEL_PATH):
                    session['excel_path'] = DEFAULT_EXCEL_PATH
                else:
                    flash(f'Default Excel file "{DEFAULT_EXCEL_PATH}" not found. Please upload an Excel file.')
                    return redirect(url_for('index'))
            else:
                # Check if custom Excel was uploaded
                if 'excel_file' in request.files and request.files['excel_file'].filename:
                    excel_file = request.files['excel_file']
                    excel_filename = secure_filename(excel_file.filename)
                    excel_temp_path = os.path.join(tempfile.gettempdir(), excel_filename)
                    excel_file.save(excel_temp_path)
                    
                    # Upload Excel to Cloudinary
                    excel_cloud_path = f"uploads/excel/{excel_filename}"
                    excel_cloud_url = cloudinary_upload(excel_cloud_path, excel_temp_path)
                    session['excel_path'] = excel_cloud_url
                    
                    # Clean up temporary Excel file
                    os.unlink(excel_temp_path)
                else:
                    flash('You selected to upload a custom Excel file, but no file was provided.')
                    return redirect(url_for('index'))
                    
            # Get manual team selections if provided
            home_team = request.form.get('home_team', '')
            away_team = request.form.get('away_team', '')
            
            # Get match day if provided
            match_day = request.form.get('match_day', '')
            if match_day:
                try:
                    match_day = int(match_day)
                    session['match_day'] = f"MD{match_day}"
                except ValueError:
                    # Invalid number, will use auto-detection
                    pass
            
            # If manual team selection was provided, store it
            if home_team:
                session['home_team'] = home_team
            
            if away_team:
                session['away_team'] = away_team
                
            # Reset the progress tracking
            reset_progress()
            
            # Redirect to the processing page instead of directly to process_video
            return redirect(url_for('show_processing'))
        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
    
    flash('File type not allowed. Please upload a video file (mp4, avi, mov, mkv).')
    return redirect(url_for('index'))

@app.route('/processing')
def show_processing():
    """Show the processing page with real-time progress updates"""
    # Check if a video path is in the session
    if 'video_path' not in session or not os.path.exists(session['video_path']):
        flash('No video found for processing')
        return redirect(url_for('index'))
    
    return render_template('processing.html')

@app.route('/confirm-teams')
def confirm_teams():
    # Get video path and Excel path from session
    video_path = session.get('video_path')
    excel_path = session.get('excel_path')
    
    if not video_path or not os.path.exists(video_path):
        flash('No video found for team confirmation')
        return redirect(url_for('index'))
    
    # Get teams from Excel
    excel_teams = get_teams_from_excel(excel_path) if excel_path else []
    
    # Detect teams from filename
    detected_home, detected_away = extract_teams_from_filename(video_path, excel_teams)
    
    # Find best matches if not already matched
    best_home_match = detected_home
    best_away_match = detected_away
    
    # Remove matched teams from dropdown options to avoid duplication
    other_teams = [team for team in excel_teams if team != best_home_match and team != best_away_match]
    
    # Extract match day from filename for display
    match_day = extract_match_day_from_filename(video_path)
    
    return render_template('confirm_teams.html', 
                          detected_home=detected_home,
                          detected_away=detected_away,
                          best_home_match=best_home_match,
                          best_away_match=best_away_match,
                          other_teams=other_teams,
                          match_day=match_day,
                          excel_teams=excel_teams)

@app.route('/confirm-teams-submit', methods=['POST'])
def confirm_teams_submit():
    # Get confirmed teams from form
    home_team = request.form.get('confirmed_home_team', '')
    away_team = request.form.get('confirmed_away_team', '')
    match_day = request.form.get('match_day', '')
    
    # Store in session
    if home_team:
        session['home_team'] = home_team
    
    if away_team:
        session['away_team'] = away_team
    
    if match_day:
        try:
            match_day_num = int(match_day)
            session['match_day'] = f"MD{match_day_num}"
        except ValueError:
            pass
    
    # Proceed to video processing
    return redirect(url_for('process_video'))

@app.route('/process', methods=['GET'])
def process_video():
    # Get video path from session
    video_path = session.get('video_path')
    excel_path = session.get('excel_path')
    
    print(f"Processing video: {video_path}")  # Debug log
    
    if not video_path:
        flash('No video found for processing. The video path was not found in session.')
        return redirect(url_for('index'))
    
    # For Cloudinary URLs, we only need to verify the URL exists, not the file
    if not video_path.startswith('http'):
        # Local path - check if it exists
        if not os.path.exists(video_path):
            flash('No video found for processing. The video file was not found.')
            return redirect(url_for('index'))
    
    # Reset progress tracking
    reset_progress()
    update_progress('initializing', 0, 'Starting processing', video_id=video_path)
    
    try:
        # Initialize OCR
        update_progress('initializing', 10, 'Initializing OCR reader', video_id=video_path)
        reader = initialize_ocr()
        
        # Get team names - either from session (manual selection) or auto-detect
        update_progress('initializing', 20, 'Determining team names', video_id=video_path)
        if session.get('home_team') and session.get('away_team'):
            home_team = session.get('home_team')
            away_team = session.get('away_team')
            update_progress('initializing', 30, f'Using selected teams: {home_team} vs {away_team}', video_id=video_path)
        else:
            # Get teams from Excel for matching
            excel_teams = get_teams_from_excel(excel_path) if excel_path else []
            
            # Extract team names from filename with fuzzy matching
            home_team, away_team = extract_teams_from_filename(video_path, excel_teams)
            update_progress('initializing', 30, f'Detected teams from filename: {home_team} vs {away_team}', video_id=video_path)
        
        # Get match day - either from session (manual input) or auto-detect
        update_progress('initializing', 40, 'Determining match day', video_id=video_path)
        if session.get('match_day'):
            match_day_value = session.get('match_day')
            update_progress('initializing', 50, f'Using selected match day: {match_day_value}', video_id=video_path)
        else:
            # Extract match day from video filename
            match_day_value = extract_match_day_from_filename(video_path)
            update_progress('initializing', 50, f'Detected match day from filename: {match_day_value}', video_id=video_path)
        
        # Check if match already exists
        existing_match_id = match_exists(home_team, away_team, match_day_value)
        if existing_match_id:
            flash(f'A match with {home_team} vs {away_team} for {match_day_value} already exists. Please view the existing match or use different teams/match day.')
            return redirect(url_for('match_stats', match_id=existing_match_id))
        
        # Extract frames
        update_progress('extracting', 0, 'Beginning frame extraction', video_id=video_path)
        frames = extract_frames(video_path, app.config['FRAMES_FOLDER'], video_id=video_path)
        
        if not frames:
            update_progress('error', 100, 'No frames were extracted from the video', video_id=video_path)
            flash('Error: No frames were extracted from the video.')
            return redirect(url_for('index'))
        
        # Identify player ratings frames and extract player names by frame
        update_progress('analyzing', 0, 'Beginning player analysis', video_id=video_path)
        
        # Modified: Track players by frame
        home_players_by_frame = {}
        away_players_by_frame = {}
        player_rating_frames = []
        detected_frames = 0
        
        # First pass: identify player rating frames
        for i, frame_path in enumerate(frames):
            # Update progress
            progress_percent = (i / len(frames)) * 60  # First pass uses 60% of progress
            update_progress('analyzing', progress_percent, 
                           f'Scanning frame {i+1}/{len(frames)}: {os.path.basename(frame_path)}',
                           video_id=video_path)
            
            # Extract text from the frame with low detail (faster)
            ocr_results = reader.readtext(frame_path, detail=1, paragraph=False)
            
            # Check if this frame contains player ratings
            contains_players = False
            text_blocks = [detection[1] for detection in ocr_results]
            combined_text = " ".join(text_blocks)
            
            if "Player Ratings" in combined_text or any("Player Rating" in text for text in text_blocks):
                contains_players = True
                player_rating_frames.append(frame_path)
                detected_frames += 1
        
        # Second pass: detailed OCR only on player rating frames
        for i, frame_path in enumerate(player_rating_frames):
            progress_percent = 60 + (i / len(player_rating_frames) * 35)
            update_progress('analyzing', progress_percent, 
                          f'Processing player ratings in frame {os.path.basename(frame_path)}',
                          detected_frames=detected_frames,
                          video_id=video_path)
            
            # Try to extract player names from cards first (more accurate)
            player_cards = extract_player_cards(frame_path, reader)
            
            # Check if this is a home or away frame
            ocr_results = extract_text_from_image(frame_path, reader)
            text_blocks = [detection[1] for detection in ocr_results]
            combined_text = " ".join(text_blocks)
            
            is_home = "Player Ratings: Home" in combined_text or any("Player Ratings: Home" in text for text in text_blocks)
            is_away = "Player Ratings: Away" in combined_text or any("Player Ratings: Away" in text for text in text_blocks)
            
            # If cards were detected, use them
            if player_cards:
                # Store the players by frame
                if is_home:
                    home_players_by_frame[frame_path] = player_cards
                    update_progress('analyzing', progress_percent, 
                                  f'Extracted {len(player_cards)} home players from cards in frame',
                                  video_id=video_path)
                elif is_away:
                    away_players_by_frame[frame_path] = player_cards
                    update_progress('analyzing', progress_percent, 
                                  f'Extracted {len(player_cards)} away players from cards in frame',
                                  video_id=video_path)
                else:
                    # If we can't determine home/away, assume home
                    home_players_by_frame[frame_path] = player_cards
                    update_progress('analyzing', progress_percent, 
                                  f'Extracted {len(player_cards)} players from cards in frame (team unknown)',
                                  video_id=video_path)
            else:
                # Fall back to regular OCR if no cards were detected
                h_players, a_players = process_text_data(ocr_results)
                
                if is_home and h_players:
                    home_players_by_frame[frame_path] = h_players
                    update_progress('analyzing', progress_percent, 
                                  f'Extracted {len(h_players)} home players from text in frame',
                                  video_id=video_path)
                elif is_away and a_players:
                    away_players_by_frame[frame_path] = a_players
                    update_progress('analyzing', progress_percent, 
                                  f'Extracted {len(a_players)} away players from text in frame',
                                  video_id=video_path)
                else:
                    # If we can't determine home/away but have players, make best guess
                    if h_players and not a_players:
                        home_players_by_frame[frame_path] = h_players
                    elif a_players and not h_players:
                        away_players_by_frame[frame_path] = a_players
                    elif h_players and a_players:
                        # Both have players, use context clues or put in both
                        if "Home" in combined_text:
                            home_players_by_frame[frame_path] = h_players + a_players
                        elif "Away" in combined_text:
                            away_players_by_frame[frame_path] = h_players + a_players
                        else:
                            # Can't determine, split them as detected
                            home_players_by_frame[frame_path] = h_players
                            away_players_by_frame[frame_path] = a_players
        
        # Clean and preprocess player names for each frame
        update_progress('analyzing', 95, 'Preprocessing player names by frame', video_id=video_path)
        
        for frame_path, players in home_players_by_frame.items():
            home_players_by_frame[frame_path] = preprocess_detected_names(players)
            
        for frame_path, players in away_players_by_frame.items():
            away_players_by_frame[frame_path] = preprocess_detected_names(players)
        
        # Store frames and player data in session for review
        session['frames'] = player_rating_frames
        session['home_players_by_frame'] = home_players_by_frame
        session['away_players_by_frame'] = away_players_by_frame
        session['home_team'] = home_team
        session['away_team'] = away_team
        session['match_day'] = match_day_value
        
        # Finalize
        update_progress('finalizing', 100, 'Processing complete, ready for review', video_id=video_path)
        
        # Redirect to review page instead of results
        return redirect(url_for('review_frames'))
    
    except Exception as e:
        update_progress('error', 100, f'Error: {str(e)}', video_id=video_path)
        flash(f'Error processing video: {str(e)}')
        traceback.print_exc()
        return redirect(url_for('index'))

@app.route('/results')
def results():
    # Get results from session
    results = session.get('results')
    
    # Debug logging
    print("==== DEBUG: /results route called ====")
    print(f"DEBUG: Results in session: {results is not None}")
    if results:
        print(f"DEBUG: Results keys: {list(results.keys())}")
        print(f"DEBUG: Home team: {results.get('home_team')}, Away team: {results.get('away_team')}")
        print(f"DEBUG: Match day: {results.get('match_day')}")
        print(f"DEBUG: Home data length: {len(results.get('home_data', {}))}")
        print(f"DEBUG: Away data length: {len(results.get('away_data', {}))}")
        print(f"DEBUG: Unmatched home count: {len(results.get('unmatched_home', []))}")
        print(f"DEBUG: Unmatched away count: {len(results.get('unmatched_away', []))}")
    
    if not results:
        flash('No results found. Please upload and process a video first.')
        return redirect(url_for('index'))
    
    # Store individual data components in session too for easier access by other routes
    session['home_team'] = results['home_team']
    session['away_team'] = results['away_team']
    session['match_day'] = results['match_day']
    session['home_data'] = results['home_data']
    session['away_data'] = results['away_data']
    session['unmatched_home'] = results['unmatched_home']
    session['unmatched_away'] = results['unmatched_away']
    
    return render_template('results.html', 
                          home_team=results['home_team'],
                          away_team=results['away_team'],
                          match_day=results['match_day'],
                          home_data=results['home_data'],
                          away_data=results['away_data'],
                          unmatched_home=results['unmatched_home'],
                          unmatched_away=results['unmatched_away'])

@app.route('/batch')
def batch_upload():
    """Show the batch upload page"""
    # Get teams from Excel for dropdown
    teams = get_teams_from_excel()
    
    # Get queue status
    queue_status = video_queue.get_status()
    
    return render_template('batch_upload.html', 
                          teams=teams, 
                          queue_status=queue_status, 
                          videos=video_queue.videos,
                          video_queue=video_queue)  # Pass the video_queue to the template

@app.route('/batch/add', methods=['POST'])
def batch_add():
    """Add videos to the batch processing queue"""
    # Check if files were uploaded
    if 'files' not in request.files:
        flash('No file part')
        return redirect(url_for('batch_upload'))
    
    files = request.files.getlist('files')
    
    if not files or files[0].filename == '':
        flash('No selected files')
        return redirect(url_for('batch_upload'))
    
    # Handle Excel file selection
    excel_path = None
    use_default_excel = request.form.get('use_default_excel', '1') == '1'
    
    if use_default_excel:
        # Check if default Excel exists
        if os.path.exists(DEFAULT_EXCEL_PATH):
            excel_path = DEFAULT_EXCEL_PATH
        else:
            flash(f'Default Excel file "{DEFAULT_EXCEL_PATH}" not found. Please upload an Excel file.')
            return redirect(url_for('batch_upload'))
    else:
        # Check if custom Excel was uploaded
        if 'excel_file' in request.files and request.files['excel_file'].filename:
            excel_file = request.files['excel_file']
            excel_path = os.path.join('static/temp', secure_filename(excel_file.filename))
            excel_file.save(excel_path)
        else:
            flash('You selected to upload a custom Excel file, but no file was provided.')
            return redirect(url_for('batch_upload'))
    
    # Get selected teams if provided
    default_home_team = request.form.get('default_home_team', '')
    default_away_team = request.form.get('default_away_team', '')
    
    # Add each valid file to the queue
    added_count = 0
    for file in files:
        if file and allowed_file(file.filename):
            # Generate a unique subfolder for each video
            video_subfolder = f"{int(time.time())}_{secure_filename(file.filename)}"
            upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], video_subfolder)
            os.makedirs(upload_dir, exist_ok=True)
            
            # Save the file
            filename = secure_filename(file.filename)
            file_path = os.path.join(upload_dir, filename)
            file.save(file_path)
            
            # Add to queue
            video_queue.add_video(
                video_path=file_path,
                excel_path=excel_path,
                home_team=default_home_team if default_home_team else None,
                away_team=default_away_team if default_away_team else None
            )
            
            added_count += 1
    
    if added_count > 0:
        flash(f'Added {added_count} videos to the processing queue.')
    else:
        flash('No valid video files were found.')
    
    return redirect(url_for('batch_upload'))

@app.route('/batch/process')
def batch_process():
    """Process the next video in the queue"""
    # Get next pending video
    video = video_queue.get_next_pending()
    
    if not video:
        flash('No pending videos in the queue.')
        return redirect(url_for('batch_processing'))
    
    try:
        # Mark as processing
        video_queue.start_processing(video['id'])
        
        # Initialize OCR
        reader = initialize_ocr()
        
        # Extract team names
        excel_teams = get_teams_from_excel(video['excel']) if video['excel'] else []
        
        # Use provided team names or detect from filename
        if video['home_team'] and video['away_team']:
            home_team = video['home_team']
            away_team = video['away_team']
        else:
            # Extract from filename with fuzzy matching
            home_team, away_team = extract_teams_from_filename(video['path'], excel_teams)
        
        # Use provided match day or detect from filename
        if video['match_day']:
            match_day_value = video['match_day']
        else:
            match_day_value = extract_match_day_from_filename(video['path'])
        
        # Check if match already exists
        existing_match_id = match_exists(home_team, away_team, match_day_value)
        match_id = existing_match_id
        
        # If match doesn't exist, create it now
        if not existing_match_id:
            # Get team data
            home_team_data = get_team_by_name(home_team)
            away_team_data = get_team_by_name(away_team)
            
            if home_team_data and away_team_data:
                match_result = create_match(
                    home_team_data["id"], 
                    away_team_data["id"], 
                    match_day_value
                )
                if match_result:
                    match_id = match_result["id"]
        
        if existing_match_id:
            video_queue.complete_processing(
                video['id'], 
                error=f'A match with {home_team} vs {away_team} for {match_day_value} already exists.'
            )
            flash(f'Skipped {video["filename"]}: Match {home_team} vs {away_team} ({match_day_value}) already exists.')
            return redirect(url_for('batch_processing'))
        
        # Create a frames subfolder for this video
        frames_dir = os.path.join(app.config['FRAMES_FOLDER'], os.path.basename(video['path']))
        os.makedirs(frames_dir, exist_ok=True)
        
        # Extract frames with video ID for progress tracking
        update_progress('extracting', 0, 'Beginning frame extraction', video_id=video['id'])
        frames = extract_frames(video['path'], frames_dir, video_id=video['id'])
        
        if not frames:
            video_queue.complete_processing(video['id'], error='No frames were extracted from the video.')
            flash(f'Error processing {video["filename"]}: No frames were extracted.')
            return redirect(url_for('batch_processing'))
        
        # Modified: Track players by frame similar to process_video function
        update_progress('analyzing', 0, 'Beginning player analysis', video_id=video['id'])
        
        # Track players by frame
        home_players_by_frame = {}
        away_players_by_frame = {}
        player_rating_frames = []
        detected_frames = 0
        
        # First pass: identify player rating frames
        for i, frame_path in enumerate(frames):
            # Update progress
            progress_percent = (i / len(frames)) * 60  # First pass uses 60% of progress
            update_progress('analyzing', progress_percent, 
                           f'Scanning frame {i+1}/{len(frames)}: {os.path.basename(frame_path)}',
                           video_id=video['id'])
            
            # Extract text from the frame with low detail (faster)
            ocr_results = reader.readtext(frame_path, detail=1, paragraph=False)
            
            # Check if this frame contains player ratings
            contains_players = False
            text_blocks = [detection[1] for detection in ocr_results]
            combined_text = " ".join(text_blocks)
            
            if "Player Ratings" in combined_text or any("Player Rating" in text for text in text_blocks):
                contains_players = True
                player_rating_frames.append(frame_path)
                detected_frames += 1
        
        # Second pass: detailed OCR only on player rating frames
        for i, frame_path in enumerate(player_rating_frames):
            progress_percent = 60 + (i / len(player_rating_frames) * 35)
            update_progress('analyzing', progress_percent, 
                          f'Processing player ratings in frame {os.path.basename(frame_path)}',
                          detected_frames=detected_frames,
                          video_id=video['id'])
            
            # Try to extract player names from cards first (more accurate)
            player_cards = extract_player_cards(frame_path, reader)
            
            # Check if this is a home or away frame
            ocr_results = extract_text_from_image(frame_path, reader)
            text_blocks = [detection[1] for detection in ocr_results]
            combined_text = " ".join(text_blocks)
            
            is_home = "Player Ratings: Home" in combined_text or any("Player Ratings: Home" in text for text in text_blocks)
            is_away = "Player Ratings: Away" in combined_text or any("Player Ratings: Away" in text for text in text_blocks)
            
            # If cards were detected, use them
            if player_cards:
                # Store the players by frame
                if is_home:
                    home_players_by_frame[frame_path] = player_cards
                    update_progress('analyzing', progress_percent, 
                                  f'Extracted {len(player_cards)} home players from cards in frame',
                                  video_id=video['id'])
                elif is_away:
                    away_players_by_frame[frame_path] = player_cards
                    update_progress('analyzing', progress_percent, 
                                  f'Extracted {len(player_cards)} away players from cards in frame',
                                  video_id=video['id'])
                else:
                    # If we can't determine home/away, assume home
                    home_players_by_frame[frame_path] = player_cards
                    update_progress('analyzing', progress_percent, 
                                  f'Extracted {len(player_cards)} players from cards in frame (team unknown)',
                                  video_id=video['id'])
            else:
                # Fall back to regular OCR if no cards were detected
                h_players, a_players = process_text_data(ocr_results)
                
                if is_home and h_players:
                    home_players_by_frame[frame_path] = h_players
                    update_progress('analyzing', progress_percent, 
                                  f'Extracted {len(h_players)} home players from text in frame',
                                  video_id=video['id'])
                elif is_away and a_players:
                    away_players_by_frame[frame_path] = a_players
                    update_progress('analyzing', progress_percent, 
                                  f'Extracted {len(a_players)} away players from text in frame',
                                  video_id=video['id'])
                else:
                    # If we can't determine home/away but have players, make best guess
                    if h_players and not a_players:
                        home_players_by_frame[frame_path] = h_players
                    elif a_players and not h_players:
                        away_players_by_frame[frame_path] = a_players
                    elif h_players and a_players:
                        # Both have players, use context clues or put in both
                        if "Home" in combined_text:
                            home_players_by_frame[frame_path] = h_players + a_players
                        elif "Away" in combined_text:
                            away_players_by_frame[frame_path] = h_players + a_players
                        else:
                            # Can't determine, split them as detected
                            home_players_by_frame[frame_path] = h_players
                            away_players_by_frame[frame_path] = a_players
        
        # Clean and preprocess player names for each frame
        update_progress('analyzing', 95, 'Preprocessing player names by frame', video_id=video['id'])
        
        for frame_path, players in home_players_by_frame.items():
            home_players_by_frame[frame_path] = preprocess_detected_names(players)
            
        for frame_path, players in away_players_by_frame.items():
            away_players_by_frame[frame_path] = preprocess_detected_names(players)
        
        # Consolidate players from all frames
        all_home_players = []
        all_away_players = []
        
        for frame_path, players in home_players_by_frame.items():
            all_home_players.extend(players)
            
        for frame_path, players in away_players_by_frame.items():
            all_away_players.extend(players)
        
        # Remove duplicates while preserving order
        unique_home_players = list(dict.fromkeys(all_home_players))
        unique_away_players = list(dict.fromkeys(all_away_players))
        
        # Prepare player data for display
        update_progress('finalizing', 0, 'Preparing results', video_id=video['id'])
        home_data, away_data, unmatched_home, unmatched_away = prepare_player_data_for_display(
            home_team, away_team, unique_home_players, unique_away_players, video['excel']
        )
        
        # Create results
        update_progress('finalizing', 75, 'Creating results', video_id=video['id'])
        results = {
            'home_team': home_team,
            'away_team': away_team,
            'match_day': match_day_value,
            'match_id': match_id,
            'home_data': home_data,
            'away_data': away_data,
            'unmatched_home': unmatched_home,
            'unmatched_away': unmatched_away,
            'frame_count': len(frames),
            'home_player_count': len(unique_home_players),
            'away_player_count': len(unique_away_players),
            'frames': player_rating_frames,
            'home_players_by_frame': home_players_by_frame,
            'away_players_by_frame': away_players_by_frame
        }
        
        # Mark as completed with results
        update_progress('finalizing', 100, 'Processing complete', video_id=video['id'])
        video_queue.complete_processing(video['id'], results)
        
        flash(f'Successfully processed {video["filename"]}')
        return redirect(url_for('batch_processing'))
    except Exception as e:
        # Handle errors
        error_message = str(e)
        traceback.print_exc()
        update_progress('error', 100, f'Error: {error_message}', video_id=video['id'])
        video_queue.complete_processing(video['id'], error=error_message)
        flash(f'Error processing {video["filename"]}: {error_message}')
    
    # Always redirect to the batch processing page to see progress
    return redirect(url_for('batch_processing'))

@app.route('/batch/status')
def batch_status():
    """Get batch processing status as JSON"""
    status = video_queue.get_status()
    return jsonify(status)

@app.route('/batch/results/<video_id>')
def batch_results(video_id):
    """Show results for a specific video"""
    video = video_queue.get_video(video_id)
    
    if not video:
        flash('Video not found')
        return redirect(url_for('batch_upload'))
    
    results = video_queue.results.get(video_id, {})
    
    if not results:
        flash('No results available for this video')
        return redirect(url_for('batch_upload'))
    
    return render_template('results.html', 
                          home_team=results['home_team'],
                          away_team=results['away_team'],
                          match_day=results['match_day'],
                          home_data=results['home_data'],
                          away_data=results['away_data'],
                          unmatched_home=results['unmatched_home'],
                          unmatched_away=results['unmatched_away'],
                          batch_mode=True,
                          video_id=video_id,
                          video_queue=video_queue)  # Pass the video_queue to the template

@app.route('/batch/remove/<video_id>')
def batch_remove(video_id):
    """Remove a video from the queue"""
    video_queue.remove_video(video_id)
    flash('Video removed from queue')
    return redirect(url_for('batch_upload') + '#queue')

@app.route('/batch/edit/<video_id>', methods=['POST'])
def batch_edit_video(video_id):
    """Edit video details in the queue"""
    # Get the video from queue
    video = video_queue.get_video(video_id)
    
    if not video:
        flash('Video not found')
        return redirect(url_for('batch_upload'))
    
    # Only allow editing pending videos
    if video['status'] != 'pending':
        flash('Only pending videos can be edited')
        return redirect(url_for('batch_upload'))
    
    # Get form data
    home_team = request.form.get('home_team', '')
    away_team = request.form.get('away_team', '')
    match_day = request.form.get('match_day', '')
    
    # Update video details
    for v in video_queue.videos:
        if v['id'] == video_id:
            v['home_team'] = home_team if home_team else None
            v['away_team'] = away_team if away_team else None
            v['match_day'] = match_day if match_day else None
            break
    
    flash('Video details updated successfully')
    return redirect(url_for('batch_upload') + '#queue')

@app.route('/batch/clear-completed')
def batch_clear_completed():
    """Clear all completed videos from the queue"""
    video_queue.clear_completed()
    flash('Cleared all completed videos from the queue')
    return redirect(url_for('batch_upload') + '#queue')

@app.route('/batch/process-all')
def batch_process_all():
    """Process all pending videos in parallel up to the maximum allowed"""
    # Get all pending videos
    pending_videos = [v for v in video_queue.videos if v['status'] == 'pending']
    
    if not pending_videos:
        flash('No pending videos in the queue.')
        return redirect(url_for('batch_processing'))
    
    # Calculate how many more videos we can process based on the max_parallel setting
    currently_processing = video_queue.count_processing()
    available_slots = video_queue.max_parallel - currently_processing
    
    if available_slots <= 0:
        flash(f'Already processing {currently_processing} videos (maximum is {video_queue.max_parallel}). Please wait for some to complete.')
        return redirect(url_for('batch_processing'))
    
    # Process only up to the available number of slots
    videos_to_process = pending_videos[:available_slots]
    
    # Start processing each video in a background thread
    for video in videos_to_process:
        video_id = video['id']
        thread = Thread(target=process_video_background, args=(video_id,))
        thread.daemon = True
        thread.start()
    
    flash(f'Started processing {len(videos_to_process)} videos in parallel (total processing: {currently_processing + len(videos_to_process)})')
    return redirect(url_for('batch_processing'))

@app.route('/batch/processing')
def batch_processing():
    """Show the batch processing progress page"""
    # Get queue status
    queue_status = video_queue.get_status()
    
    # Get current processing video if any
    current_video = None
    for video in video_queue.videos:
        if video['status'] == 'processing':
            current_video = video
            break
    
    return render_template('batch_processing.html', 
                          queue_status=queue_status,
                          videos=video_queue.videos,
                          current_video=current_video,
                          progress=progress,
                          video_queue=video_queue)  # Pass the video_queue to the template

@app.route('/progress')
def get_progress():
    """Return the current progress as JSON"""
    return jsonify(progress)

@app.route('/progress/<video_id>')
def get_video_progress(video_id):
    """Return the progress for a specific video as JSON"""
    if video_id in progress['videos']:
        return jsonify(progress['videos'][video_id])
    else:
        return jsonify({
            'current_stage': 'unknown',
            'percent': 0,
            'message': 'Video not found or not processing yet'
        })

@app.route('/progress/reset')
def reset_progress():
    """Reset the progress tracking"""
    global progress
    progress = {
        'current_stage': 'idle',
        'percent': 0,
        'message': 'Ready to process',
        'current_frame': 0,
        'total_frames': 0,
        'detected_frames': 0,
        'home_players': [],
        'away_players': [],
        'videos': {}  # Store progress for each video by ID
    }
    return jsonify({"status": "reset"})

@app.route('/auto-update-excel', methods=['POST'])
def auto_update_excel():
    """
    Automatically update Excel and save player appearance data to database
    All unmatched players will be saved to the unmatched_players table.
    """
    # Debug logging
    print("==== DEBUG: auto_update_excel called ====")
    
    # Check if results exist in session
    if 'results' not in session:
        flash('No results data found. Please process a video first.')
        return redirect(url_for('index'))
    
    # Get all data from results
    results = session.get('results', {})
    home_team = results.get('home_team', '')
    away_team = results.get('away_team', '')
    match_day_value = results.get('match_day', 'MD1')
    home_data = results.get('home_data', {})
    away_data = results.get('away_data', {})
    unmatched_home = results.get('unmatched_home', [])
    unmatched_away = results.get('unmatched_away', [])
    
    # Debug logging
    print(f"DEBUG: Using data from 'results' session key")
    print(f"DEBUG: Home team: {home_team}, Away team: {away_team}")
    print(f"DEBUG: Match day: {match_day_value}")
    print(f"DEBUG: Home data: {home_data}")
    print(f"DEBUG: Away data: {away_data}")
    print(f"DEBUG: Unmatched home players: {unmatched_home}")
    print(f"DEBUG: Unmatched away players: {unmatched_away}")
    
    # Get player positions
    home_positions = results.get('home_positions', {})
    away_positions = results.get('away_positions', {})
    
    # Keep track of how many players we process
    home_added = 0
    away_added = 0
    home_appearances = 0
    away_appearances = 0
    match_id = None
    
    try:
        home_team_data = get_team_by_name(home_team)
        away_team_data = get_team_by_name(away_team)
        
        print(f"DEBUG: Home team data found: {home_team_data is not None}")
        print(f"DEBUG: Away team data found: {away_team_data is not None}")
        
        if home_team_data and away_team_data:
            match_result = create_match(
                home_team_data["id"], 
                away_team_data["id"], 
                match_day_value
            )
            if match_result:
                match_id = match_result["id"]
                print(f"Created match record: {home_team} vs {away_team} for {match_day_value}")
    except Exception as e:
        print(f"Error creating match record: {e}")
        traceback.print_exc()
    
    # Add ALL unmatched players to the unmatched_players table
    home_added = 0
    away_added = 0
    
    if home_team_data:
        home_team_id = home_team_data["id"]
        # Add all unmatched players from home team
        for player_name in unmatched_home:
            position = home_positions.get(player_name, "Unknown")
            unmatched_player = add_unmatched_player(player_name, home_team_id, match_day_value, position, match_id)
            if unmatched_player:
                home_added += 1
                print(f"Added unmatched player: {player_name} ({position}) to {home_team} for {match_day_value}")

    if away_team_data:
        away_team_id = away_team_data["id"]
        # Add all unmatched players from away team 
        for player_name in unmatched_away:
            position = away_positions.get(player_name, "Unknown")
            unmatched_player = add_unmatched_player(player_name, away_team_id, match_day_value, position, match_id)
            if unmatched_player:
                away_added += 1
                print(f"Added unmatched player: {player_name} ({position}) to {away_team} for {match_day_value}")
    
    # Record appearances for all existing players that were detected in the video
    home_appearances = 0
    away_appearances = 0
    
    try:
        # Process home team appearances
        if home_team_data:
            home_team_id = home_team_data["id"]
            # Get all players for home team
            home_team_players = get_players_by_team(home_team_id)
            
            # Record appearances for existing players that were found in the video
            for player in home_team_players:
                player_name = player["name"]
                print(f"DEBUG: Checking home player {player_name}, in home_data: {player_name in home_data}, value: {home_data.get(player_name)}")
                # Check if player was detected in the video - accept any truthy value
                if player_name in home_data and home_data[player_name]:
                    # Record appearance
                    update_player_appearance(player["id"], match_day_value, True, match_id)
                    home_appearances += 1
                    print(f"Recorded appearance for {player_name} ({home_team}) on {match_day_value}")
        
        # Process away team appearances
        if away_team_data:
            away_team_id = away_team_data["id"]
            # Get all players for away team
            away_team_players = get_players_by_team(away_team_id)
            
            # Record appearances for existing players that were found in the video
            for player in away_team_players:
                player_name = player["name"]
                print(f"DEBUG: Checking away player {player_name}, in away_data: {player_name in away_data}, value: {away_data.get(player_name)}")
                # Check if player was detected in the video - accept any truthy value
                if player_name in away_data and away_data[player_name]:
                    # Record appearance
                    update_player_appearance(player["id"], match_day_value, True, match_id)
                    away_appearances += 1
                    print(f"Recorded appearance for {player_name} ({away_team}) on {match_day_value}")
    
    except Exception as e:
        print(f"Error recording appearances: {e}")
        traceback.print_exc()
    
    # Flash success message
    total_appearances = home_appearances + away_appearances
    unmatched_count = home_added + away_added
    
    if unmatched_count > 0 or total_appearances > 0:
        flash(f'Successfully saved {total_appearances} player appearances and added {unmatched_count} unmatched players to the database')
    else:
        flash('No new players or appearances were added to the database')
    
    return redirect(url_for('results'))

@app.route('/unmatched-players')
def unmatched_players():
    """
    Display all unmatched players
    """
    try:
        # Get all unmatched players
        players = get_unmatched_players()
        
        # Group by team for better display
        teams_dict = {}
        for player in players:
            team_name = player.get("team_name", "Unknown Team")
            if team_name not in teams_dict:
                teams_dict[team_name] = []
            teams_dict[team_name].append(player)
        
        return render_template('unmatched_players.html', 
                             teams_dict=teams_dict,
                             total_players=len(players))
    except Exception as e:
        flash(f'Error retrieving unmatched players: {str(e)}')
        return redirect(url_for('index'))

@app.route('/unmatched-players/team/<team_id>')
def unmatched_players_by_team(team_id):
    """
    Display unmatched players for a specific team
    """
    try:
        # Get team details
        team = get_team_by_id(team_id)
        if not team:
            flash('Team not found')
            return redirect(url_for('unmatched_players'))
        
        # Get unmatched players for this team
        players = get_unmatched_players_by_team(team_id)
        
        return render_template('unmatched_players_team.html',
                             team=team,
                             players=players,
                             total_players=len(players))
    except Exception as e:
        flash(f'Error retrieving unmatched players: {str(e)}')
        return redirect(url_for('unmatched_players'))

# Add this after the names_match function

# Custom lookup for known player names to fix common OCR errors
def lookup_player_name(detected_name, known_players=None):
    """
    Try to match a detected player name against a known list of player names
    Returns the matched name from the known list, or the original if no match found
    
    Parameters:
    detected_name - Name detected from OCR
    known_players - Dictionary of known player names, keyed by team name (optional)
    """
    # If no known players provided, just return the original name
    if not known_players:
        return detected_name
    
    # Normalize the detected name
    norm_detected = normalize_player_name(detected_name)
    if not norm_detected:
        return detected_name
    
    # For each team in known players
    best_match = None
    best_score = 0
    
    # Flatten the dictionary for easier lookup
    all_known_players = []
    for team, players in known_players.items():
        all_known_players.extend(players)
    
    # Remove duplicates
    all_known_players = list(set(all_known_players))
    
    # Use fuzzy matching to find the best match
    from fuzzywuzzy import process
    match_result = process.extractOne(norm_detected, all_known_players, 
                                     scorer=lambda x, y: max(
                                         fuzz.ratio(x, y),
                                         fuzz.token_sort_ratio(x, y),
                                         fuzz.token_set_ratio(x, y),
                                         fuzz.partial_ratio(x, y)
                                     ))
    
    if match_result and match_result[1] >= 80:  # 80% similarity threshold
        return match_result[0]
    
    # If no good match, check if the detected name is a substring of a known name
    for known_name in all_known_players:
        norm_known = normalize_player_name(known_name)
        if norm_detected in norm_known and len(norm_detected) >= 3:
            if len(norm_detected) / len(norm_known) > 0.6:  # Must be a substantial part of the name
                return known_name
    
    # If no match found, return the original name
    return detected_name

@app.route('/batch/results-all')
def batch_results_all():
    """Show results for all completed videos in a single page"""
    # Get all completed videos
    completed_videos = [v for v in video_queue.videos if v['status'] == 'completed']
    
    if not completed_videos:
        flash('No completed videos found')
        return redirect(url_for('batch_upload'))
    
    # Extract results for all completed videos
    batch_results = []
    for video in completed_videos:
        video_id = video.get('id')
        results = video_queue.results.get(video_id, {})
        if results:
            # Ensure all required fields exist in the results dictionary
            sanitized_results = {
                'video': {
                    'id': video['id'],
                    'filename': video['filename'],
                    'processed_at': video['processed_at'] or 'Unknown'
                },
                'home_team': results.get('home_team', 'Unknown'),
                'away_team': results.get('away_team', 'Unknown'),
                'match_day': results.get('match_day', 'Unknown'),
                'home_data': results.get('home_data', {}),
                'away_data': results.get('away_data', {}),
                'unmatched_home': results.get('unmatched_home', []),
                'unmatched_away': results.get('unmatched_away', [])
            }
            batch_results.append(sanitized_results)
    
    # Check if we have results
    if not batch_results:
        flash('No result data found for completed videos')
        return redirect(url_for('batch_upload'))
    
    # Sort the results in a consistent order:
    # 1. First by match day (if in MDx format, extract the number)
    # 2. Then by home team name
    # 3. Finally by away team name
    def sort_key(result):
        # Extract match day number if in MDx format
        match_day = result.get('match_day', '')
        match_day_num = 0
        if isinstance(match_day, str) and match_day.startswith('MD'):
            try:
                match_day_num = int(match_day[2:])
            except ValueError:
                match_day_num = 0
        
        return (match_day_num, result.get('home_team', ''), result.get('away_team', ''))
    
    # Apply the sorting
    batch_results.sort(key=sort_key)
    
    # Log the sorted batch results for debugging
    app.logger.info(f"Displaying {len(batch_results)} batch results in sorted order")
    for i, result in enumerate(batch_results):
        app.logger.debug(f"Result {i+1}: {result.get('home_team')} vs {result.get('away_team')} ({result.get('match_day')})")
    
    return render_template('batch_results_all.html', 
                          batch_results=batch_results,
                          queue_status=video_queue.get_status())

def process_video_background(video_id):
    """Process a video in the background"""
    try:
        # Get the video from the queue
        video = None
        for v in video_queue.videos:
            if v['id'] == video_id:
                video = v
                break
                
        if not video:
            print(f"Error: Video with id {video_id} not found in queue")
            return
            
        # Mark as processing
        video_queue.start_processing(video_id)
        
        # Initialize OCR
        reader = initialize_ocr()
        
        # Extract team names
        excel_teams = get_teams_from_excel(video['excel']) if video['excel'] else []
        
        # Use provided team names or detect from filename
        if video['home_team'] and video['away_team']:
            home_team = video['home_team']
            away_team = video['away_team']
        else:
            # Extract from filename with fuzzy matching
            home_team, away_team = extract_teams_from_filename(video['path'], excel_teams)
        
        # Use provided match day or detect from filename
        if video['match_day']:
            match_day_value = video['match_day']
        else:
            match_day_value = extract_match_day_from_filename(video['path'])
        
        # Check if match already exists
        existing_match_id = match_exists(home_team, away_team, match_day_value)
        match_id = existing_match_id
        
        # If match doesn't exist, create it now
        if not existing_match_id:
            # Get team data
            home_team_data = get_team_by_name(home_team)
            away_team_data = get_team_by_name(away_team)
            
            if home_team_data and away_team_data:
                match_result = create_match(
                    home_team_data["id"], 
                    away_team_data["id"], 
                    match_day_value
                )
                if match_result:
                    match_id = match_result["id"]
        
        if existing_match_id:
            video_queue.complete_processing(
                video_id, 
                error=f'A match with {home_team} vs {away_team} for {match_day_value} already exists.'
            )
            print(f'Skipped {video["filename"]}: Match {home_team} vs {away_team} ({match_day_value}) already exists.')
            return
        
        # Create a frames subfolder for this video
        frames_dir = os.path.join(app.config['FRAMES_FOLDER'], os.path.basename(video['path']))
        os.makedirs(frames_dir, exist_ok=True)
        
        # Extract frames with video ID for progress tracking
        update_progress('extracting', 0, 'Beginning frame extraction', video_id=video_id)
        frames = extract_frames(video['path'], frames_dir, video_id=video_id)
        
        if not frames:
            video_queue.complete_processing(video_id, error='No frames were extracted from the video.')
            print(f'Error processing {video["filename"]}: No frames were extracted.')
            return
        
        # Identify player ratings frames and extract player names
        update_progress('analyzing', 0, 'Beginning player analysis', video_id=video_id)
        home_players, away_players = identify_player_ratings_frames(frames, reader, video_id=video_id)
        
        # Prepare player data for display
        update_progress('finalizing', 0, 'Preparing results', video_id=video_id)
        home_data, away_data, unmatched_home, unmatched_away = prepare_player_data_for_display(
            home_team, away_team, home_players, away_players, video['excel']
        )
        
        # Create results
        update_progress('finalizing', 75, 'Creating results', video_id=video_id)
        results = {
            'home_team': home_team,
            'away_team': away_team,
            'match_day': match_day_value,
            'match_id': match_id,
            'home_data': home_data,
            'away_data': away_data,
            'unmatched_home': unmatched_home,
            'unmatched_away': unmatched_away,
            'frame_count': len(frames),
            'home_player_count': len(home_players),
            'away_player_count': len(away_players)
        }
        
        # Mark as completed with results
        update_progress('finalizing', 100, 'Processing complete', video_id=video_id)
        video_queue.complete_processing(video_id, results)
        
        print(f'Successfully processed {video["filename"]}')
    except Exception as e:
        # Handle errors
        error_message = str(e)
        traceback.print_exc()
        update_progress('error', 100, f'Error: {error_message}', video_id=video_id)
        video_queue.complete_processing(video_id, error=error_message)
        print(f'Error processing {video["filename"]}: {error_message}')

@app.route('/batch/configure', methods=['POST'])
def batch_configure():
    """Update batch processing configuration settings"""
    # Update max parallel processing setting
    if 'max_parallel' in request.form:
        try:
            max_parallel = int(request.form['max_parallel'])
            if 1 <= max_parallel <= 8:  # Limit to reasonable range
                video_queue.max_parallel = max_parallel
                flash(f'Updated maximum parallel processing to {max_parallel} videos')
            else:
                flash('Invalid value for maximum parallel processing')
        except ValueError:
            flash('Invalid value for maximum parallel processing')
    
    return redirect(url_for('batch_upload'))

@app.route('/teams')
def teams():
    """
    Display a list of all teams with links to their statistics
    """
    try:
        teams = get_teams()
        return render_template('teams.html', teams=teams)
    except Exception as e:
        flash(f'Error retrieving teams: {str(e)}')
        return redirect(url_for('index'))

@app.route('/team_stats/<team_id>')
def team_stats(team_id):
    """
    Display appearance statistics for a specific team
    """
    try:
        # Get team details
        team = None
        for t in get_teams():
            if t["id"] == team_id:
                team = t
                break
        
        if not team:
            flash('Team not found')
            return redirect(url_for('index'))
        
        # Get team appearance statistics
        player_stats = get_team_appearance_stats(team_id)
        
        return render_template('team_stats.html', 
                              team=team,
                              players=player_stats)
    
    except Exception as e:
        flash(f'Error retrieving team statistics: {str(e)}')
        return redirect(url_for('index'))

@app.route('/team_matches/<team_id>')
def team_matches(team_id):
    """
    Display all matches for a specific team with player appearances
    """
    try:
        # Get team details
        team = None
        for t in get_teams():
            if t["id"] == team_id:
                team = t
                break
        
        if not team:
            flash('Team not found')
            return redirect(url_for('index'))
        
        # Get all matches for this team (both home and away)
        matches = get_team_matches(team_id)
        
        return render_template('team_matches.html', 
                              team=team,
                              matches=matches)
    
    except Exception as e:
        flash(f'Error retrieving team matches: {str(e)}')
        return redirect(url_for('index'))

@app.route('/match_stats/<match_id>')
def match_stats(match_id):
    """
    Show the statistics for a specific match
    """
    try:
        # Get match details
        match_data = get_match_appearance_stats(match_id)
        if not match_data:
            flash('Match not found')
            return redirect(url_for('teams'))
            
        # Get team information from match data
        home_team_id = match_data["match"]["home_team_id"]
        away_team_id = match_data["match"]["away_team_id"]
        
        # Get team details
        home_team = get_team_by_id(home_team_id)
        away_team = get_team_by_id(away_team_id)
        
        if not home_team or not away_team:
            flash('Team information not found')
            return redirect(url_for('teams'))
            
        # Get unmatched players specific to this match
        unmatched_players = get_unmatched_players(match_id)
        
        # Group unmatched players by team for display
        teams_unmatched = {}
        for player in unmatched_players:
            team_name = player.get("team_name", "Unknown Team")
            if team_name not in teams_unmatched:
                teams_unmatched[team_name] = []
            teams_unmatched[team_name].append(player)
        
        return render_template('match_stats.html', 
                             match=match_data["match"], 
                             home_team=home_team,
                             away_team=away_team,
                             home_players=match_data["home_players"],
                             away_players=match_data["away_players"],
                             match_id=match_id,
                             teams_unmatched=teams_unmatched,
                             total_unmatched=len(unmatched_players))
    except Exception as e:
        print(f"Error retrieving match details: {str(e)}")
        traceback.print_exc()
        flash(f'Error retrieving match details: {str(e)}')
        return redirect(url_for('teams'))

@app.route('/export_excel')
def export_excel():
    """
    Export player appearances to an Excel file in the same format as APPEARANCE.xlsx
    Each team will have its own worksheet
    """
    try:
        print("Starting Excel export process...")
        
        # Make sure temp directory exists
        temp_dir = os.path.join('static', 'temp')
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir, exist_ok=True)
            print(f"Created temp directory: {temp_dir}")
            
        # Create a new Excel workbook
        wb = Workbook()
        print("Created Excel workbook")
        
        # Remove the default sheet
        default_sheet = wb.active
        wb.remove(default_sheet)
        print("Removed default sheet")
        
        # Get all teams and their players
        teams = get_teams()
        print(f"Retrieved {len(teams)} teams from database")
        
        # Process each team and create a separate worksheet for each
        for team in teams:
            team_id = team["id"]
            team_name = team["name"]
            
            print(f"Processing team: {team_name}")
            
            # Excel worksheet names have a 31 character limit and can't contain certain characters
            safe_name = re.sub(r'[\[\]:*?/\\]', '', team_name)  # Remove invalid chars
            if len(safe_name) > 31:
                safe_name = safe_name[:31]  # Truncate if too long
            
            # Create a worksheet for this team
            ws = wb.create_sheet(title=safe_name)
            
            # Set up column headers for match days
            ws.cell(row=1, column=1, value="PLAYER")
            ws.cell(row=1, column=2, value="POSITION")
            ws.cell(row=1, column=3, value="STATUS")
            ws.cell(row=1, column=4, value="MD1")
            ws.cell(row=1, column=5, value="MD2")
            ws.cell(row=1, column=6, value="MD3")
            ws.cell(row=1, column=7, value="MD4")
            ws.cell(row=1, column=8, value="MD5")
            
            # Get appearance stats for this team
            player_stats = get_team_appearance_stats(team_id)
            print(f"Retrieved {len(player_stats)} players for team {team_name}")
            
            # Starting row for data
            row = 2
            
            # Add each player to the spreadsheet
            for player in player_stats:
                # Player name
                ws.cell(row=row, column=1, value=player["name"])
                
                # Position
                ws.cell(row=row, column=2, value=player.get("position", "Unknown"))
                
                # Status (Active/Inactive)
                ws.cell(row=row, column=3, value=player.get("status", "Active"))
                
                # Get appearances for this player
                appearances_list = player.get("appearances_list", [])
                
                # Create a dictionary to easily check if a player appeared in each match day
                md_appearances = {}
                for appearance in appearances_list:
                    md = appearance.get("match_day")
                    if md and appearance.get("appeared", False):
                        md_appearances[md] = True
                
                # Add each match day appearance (1 for appeared, blank for not appeared)
                for md_num in range(1, 6):
                    md_key = f"MD{md_num}"
                    # Check if the player has an appearance for this match day
                    has_appearance = md_appearances.get(md_key, False)
                    
                    # Write 1 for appearance, leave blank for no appearance
                    value = 1 if has_appearance else None
                    ws.cell(row=row, column=3+md_num, value=value)
                
                # Move to next row
                row += 1
            
            print(f"Completed worksheet for team {team_name}")
        
        # Add a sheet for unmatched players
        try:
            print("Attempting to add unmatched players...")
            # Get all unmatched players
            unmatched_players = get_unmatched_players()
            print(f"Retrieved {len(unmatched_players)} unmatched players")
            
            if unmatched_players:
                # Create a sheet for unmatched players
                ws_unmatched = wb.create_sheet(title="Unmatched Players")
                
                # Set up headers
                ws_unmatched.cell(row=1, column=1, value="TEAM")
                ws_unmatched.cell(row=1, column=2, value="PLAYER")
                ws_unmatched.cell(row=1, column=3, value="POSITION")
                ws_unmatched.cell(row=1, column=4, value="MATCH DAY")
                ws_unmatched.cell(row=1, column=5, value="DETECTED ON")
                
                # Add unmatched players
                u_row = 2
                for player in unmatched_players:
                    ws_unmatched.cell(row=u_row, column=1, value=player.get("team_name", "Unknown"))
                    ws_unmatched.cell(row=u_row, column=2, value=player.get("name", "Unknown"))
                    ws_unmatched.cell(row=u_row, column=3, value=player.get("position", "Unknown"))
                    ws_unmatched.cell(row=u_row, column=4, value=player.get("match_day", "Unknown"))
                    ws_unmatched.cell(row=u_row, column=5, value=player.get("created_at", ""))
                    u_row += 1
        except Exception as e:
            print(f"Error adding unmatched players to Excel: {str(e)}")
            traceback.print_exc()
            # Continue without adding unmatched players
            
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Player_Appearances_{timestamp}.xlsx"
        filepath = os.path.join('static/temp', filename)
        print(f"Saving workbook to: {filepath}")
        
        # Save the workbook
        wb.save(filepath)
        print(f"Workbook saved successfully")
        
        # Check if file exists before sending
        if not os.path.exists(filepath):
            print(f"ERROR: File does not exist after saving: {filepath}")
            raise FileNotFoundError(f"Excel file was not created: {filepath}")
            
        # Return the file for download
        print(f"Sending file for download: {filename}")
        return send_file(
            filepath,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True, 
            download_name=filename
        )
        
    except Exception as e:
        print(f"ERROR in export_excel: {str(e)}")
        traceback.print_exc()
        flash(f'Error exporting to Excel: {str(e)}')
        return redirect(url_for('index'))

@app.route('/download_excel/<filename>')
def download_excel(filename):
    """
    Download the generated Excel file
    """
    try:
        filepath = os.path.join('static/temp', filename)
        if not os.path.exists(filepath):
            flash('Excel file not found')
            return redirect(url_for('index'))
            
        # Return the file for download
        return redirect(url_for('static', filename=f'temp/{filename}'))
        
    except Exception as e:
        flash(f'Error downloading Excel file: {str(e)}')
        return redirect(url_for('index'))

@app.route('/test_excel_download')
def test_excel_download():
    """
    Simple test route that creates a basic Excel file and sends it for download
    Use this to test if the file download mechanism is working
    """
    try:
        print("Starting simple Excel test...")
        
        # Make sure temp directory exists
        temp_dir = os.path.join('static', 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        
        # Create a very simple Excel workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Test Sheet"
        
        # Add some sample data
        ws.cell(row=1, column=1, value="Test Data")
        ws.cell(row=2, column=1, value="This is a test Excel file")
        ws.cell(row=3, column=1, value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        
        # Save to a file
        filename = f"Test_Excel_{int(time.time())}.xlsx"
        filepath = os.path.join(temp_dir, filename)
        print(f"Saving test file to: {filepath}")
        wb.save(filepath)
        
        # Check if file exists
        if not os.path.exists(filepath):
            print(f"ERROR: Test file was not created at {filepath}")
            raise FileNotFoundError("Test Excel file was not created")
            
        print(f"Test file created successfully: {filepath}")
        
        # Return the file directly
        print("Attempting to send file for download...")
        response = send_file(
            filepath,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
        print("send_file function completed")
        return response
        
    except Exception as e:
        print(f"ERROR in test_excel_download: {str(e)}")
        traceback.print_exc()
        flash(f'Error in test Excel download: {str(e)}')
        return redirect(url_for('index'))

@app.route('/export_excel_alt')
def export_excel_alt():
    """
    Alternative Excel export method that creates the file but redirects
    to a download link instead of using send_file
    """
    try:
        print("Starting alternative Excel export...")
        
        # Make sure temp directory exists
        temp_dir = os.path.join('static', 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        
        # Create a new Excel workbook
        wb = Workbook()
        
        # Remove the default sheet
        default_sheet = wb.active
        wb.remove(default_sheet)
        
        # Get all teams and their players
        teams = get_teams()
        print(f"Retrieved {len(teams)} teams from database")
        
        # Process each team and create a separate worksheet for each
        for team in teams:
            team_id = team["id"]
            team_name = team["name"]
            
            # Excel worksheet names have a 31 character limit and can't contain certain characters
            safe_name = re.sub(r'[\[\]:*?/\\]', '', team_name)  # Remove invalid chars
            if len(safe_name) > 31:
                safe_name = safe_name[:31]  # Truncate if too long
            
            # Create a worksheet for this team
            ws = wb.create_sheet(title=safe_name)
            
            # Set up column headers for match days
            ws.cell(row=1, column=1, value="PLAYER")
            ws.cell(row=1, column=2, value="POSITION")
            ws.cell(row=1, column=3, value="STATUS")
            ws.cell(row=1, column=4, value="MD1")
            ws.cell(row=1, column=5, value="MD2")
            ws.cell(row=1, column=6, value="MD3")
            ws.cell(row=1, column=7, value="MD4")
            ws.cell(row=1, column=8, value="MD5")
            
            # Get appearance stats for this team
            player_stats = get_team_appearance_stats(team_id)
            
            # Starting row for data
            row = 2
            
            # Add each player to the spreadsheet
            for player in player_stats:
                # Player name
                ws.cell(row=row, column=1, value=player["name"])
                
                # Position
                ws.cell(row=row, column=2, value=player.get("position", "Unknown"))
                
                # Status (Active/Inactive)
                ws.cell(row=row, column=3, value=player.get("status", "Active"))
                
                # Get appearances for this player
                appearances_list = player.get("appearances_list", [])
                
                # Create a dictionary to easily check if a player appeared in each match day
                md_appearances = {}
                for appearance in appearances_list:
                    md = appearance.get("match_day")
                    if md and appearance.get("appeared", False):
                        md_appearances[md] = True
                
                # Add each match day appearance (1 for appeared, blank for not appeared)
                for md_num in range(1, 6):
                    md_key = f"MD{md_num}"
                    # Check if the player has an appearance for this match day
                    has_appearance = md_appearances.get(md_key, False)
                    
                    # Write 1 for appearance, leave blank for no appearance
                    value = 1 if has_appearance else None
                    ws.cell(row=row, column=3+md_num, value=value)
                
                # Move to next row
                row += 1
        
        # Add unmatched players
        try:
            unmatched_players = get_unmatched_players()
            if unmatched_players:
                # Create a sheet for unmatched players
                    ws_unmatched = wb.create_sheet(title="Unmatched Players")
                
                # Set up headers
                    ws_unmatched.cell(row=1, column=1, value="TEAM")
                    ws_unmatched.cell(row=1, column=2, value="PLAYER")
                    ws_unmatched.cell(row=1, column=3, value="POSITION")
                    ws_unmatched.cell(row=1, column=4, value="MATCH DAY")
                    ws_unmatched.cell(row=1, column=5, value="DETECTED ON")
                    
                # Add unmatched players
                    u_row = 2
                    for player in unmatched_players:
                        ws_unmatched.cell(row=u_row, column=1, value=player.get("team_name", "Unknown"))
                        ws_unmatched.cell(row=u_row, column=2, value=player.get("name", "Unknown"))
                        ws_unmatched.cell(row=u_row, column=3, value=player.get("position", "Unknown"))
                        ws_unmatched.cell(row=u_row, column=4, value=player.get("match_day", "Unknown"))
                        ws_unmatched.cell(row=u_row, column=5, value=player.get("created_at", ""))
                        u_row += 1
        except Exception as e:
            print(f"Error adding unmatched players: {str(e)}")
            
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Player_Appearances_{timestamp}.xlsx"
        filepath = os.path.join('static/temp', filename)
        
        # Save the workbook
        wb.save(filepath)
        print(f"Workbook saved successfully to {filepath}")
        
        # Store the filename in the session
        session['excel_filename'] = filename
        
        # Redirect to a page that provides a download link
        flash('Excel file created successfully. Click the download button below.')
        return render_template('excel_download.html', filename=filename)
        
    except Exception as e:
        print(f"ERROR in export_excel_alt: {str(e)}")
        traceback.print_exc()
        flash(f'Error exporting to Excel: {str(e)}')
        return redirect(url_for('index'))

@app.route('/admin_edit_match/<match_id>', methods=['GET', 'POST'])
def admin_edit_match(match_id):
    """
    Admin interface for editing match results and player appearances
    """
    try:
        # Get match details and team IDs in a single query
        supabase = get_supabase_client()
        match_response = supabase.table("matches").select("*").eq("id", match_id).execute()
        
        if not match_response.data:
            flash('Match not found')
            return redirect(url_for('index'))
            
        match_data = match_response.data[0]
        home_team_id = match_data.get("home_team_id")
        away_team_id = match_data.get("away_team_id")
        
        # Get both teams in parallel (avoiding sequential queries)
        home_team = get_team_by_id(home_team_id)
        away_team = get_team_by_id(away_team_id)
        
        if not home_team or not away_team:
            flash('Team information not found')
            return redirect(url_for('index'))
        
        # Handle form submission
        if request.method == 'POST':
            try:
                # Process form data here for updating match details
                # This would typically involve updating player appearances
                flash('Match details updated successfully')
                return redirect(url_for('match_stats', match_id=match_id))
            except Exception as e:
                flash(f'Error updating match: {str(e)}')
        
        # Get all players for both teams in parallel
        all_home_players = get_players_by_team(home_team_id)
        all_away_players = get_players_by_team(away_team_id)
        
        # Get all appearances for this match in one query
        all_appearances = supabase.table("appearances").select("*").eq("match_id", match_id).execute()
        
        # Create dictionaries of player appearances for faster lookup
        player_appearances = {}
        if all_appearances.data:
            for appearance in all_appearances.data:
                player_id = appearance.get("player_id")
                if player_id:
                    player_appearances[player_id] = appearance.get("appeared", False)
        
        # Get IDs of players who appeared in this match
        home_appeared_ids = []
        away_appeared_ids = []
        
        # Use the direct appearance data to determine who appeared
        for player in all_home_players:
            player_id = player.get("id")
            if player_id in player_appearances and player_appearances[player_id]:
                home_appeared_ids.append(player_id)
                
        for player in all_away_players:
            player_id = player.get("id")
            if player_id in player_appearances and player_appearances[player_id]:
                away_appeared_ids.append(player_id)
        
        # Get player details for those who appeared - more efficiently
        # Create player lookups by ID for faster access
        home_player_lookup = {p["id"]: p for p in all_home_players}
        away_player_lookup = {p["id"]: p for p in all_away_players}
        
        # Build the detailed player lists for the ones who appeared
        home_players = []
        for player_id in home_appeared_ids:
            if player_id in home_player_lookup:
                home_players.append(home_player_lookup[player_id])
                
        away_players = []
        for player_id in away_appeared_ids:
            if player_id in away_player_lookup:
                away_players.append(away_player_lookup[player_id])
        
        return render_template('admin_edit_results.html',
                              match=match_data,
                              home_team=home_team,
                              away_team=away_team,
                              home_players=home_players,
                              away_players=away_players,
                              all_home_players=all_home_players,
                              all_away_players=all_away_players,
                              home_appeared_ids=home_appeared_ids,
                              away_appeared_ids=away_appeared_ids)
    
    except Exception as e:
        flash(f'Error retrieving match for editing: {str(e)}')
        traceback.print_exc()  # Add traceback for better debugging
        return redirect(url_for('index'))

@app.route('/admin_update_results/<match_id>', methods=['POST'])
def admin_update_results(match_id):
    """
    Process form submission for updating player appearances in a match
    """
    try:
        # Get match details
        match_stats = get_match_appearance_stats(match_id)
        if not match_stats:
            flash('Match not found')
            return redirect(url_for('index'))
            
        # Get team IDs
        home_team_id = match_stats["match"]["home_team_id"]
        away_team_id = match_stats["match"]["away_team_id"]
        match_day = match_stats["match"]["match_day"]
        
        # Get all existing players
        home_players = get_players_by_team(home_team_id)
        away_players = get_players_by_team(away_team_id)
        
        # Process home team player appearances
        for player in home_players:
            player_id = player["id"]
            field_name = f'home_player_{player_id}'
            
            # Check if player appeared (checkbox checked)
            appeared = field_name in request.form
            
            # Update player appearance
            update_player_appearance(player_id, match_day, appeared, match_id)
        
        # Process away team player appearances
        for player in away_players:
            player_id = player["id"]
            field_name = f'away_player_{player_id}'
            
            # Check if player appeared (checkbox checked)
            appeared = field_name in request.form
            
            # Update player appearance
            update_player_appearance(player_id, match_day, appeared, match_id)
        
        # Process new player additions for home team
        new_home_player_name = request.form.get('new_home_player_name', '').strip()
        if new_home_player_name:
            position = request.form.get('new_home_player_position', 'Unknown')
            appeared = 'new_home_player_appeared' in request.form
            
            # Add new player
            new_player = add_new_player(new_home_player_name, home_team_id, position, "Active")
            if new_player and appeared:
                update_player_appearance(new_player["id"], match_day, True, match_id)
        
        # Process new player additions for away team
        new_away_player_name = request.form.get('new_away_player_name', '').strip()
        if new_away_player_name:
            position = request.form.get('new_away_player_position', 'Unknown')
            appeared = 'new_away_player_appeared' in request.form
            
            # Add new player
            new_player = add_new_player(new_away_player_name, away_team_id, position, "Active")
            if new_player and appeared:
                update_player_appearance(new_player["id"], match_day, True, match_id)
        
        flash('Match results updated successfully')
        return redirect(url_for('match_stats', match_id=match_id))
    
    except Exception as e:
        flash(f'Error updating match results: {str(e)}')
        traceback.print_exc()
        return redirect(url_for('match_stats', match_id=match_id))

@app.route('/admin_update_match/<match_id>', methods=['POST'])
def admin_update_match(match_id):
    """
    Process form submission for updating match details
    """
    try:
        # Get form data
        match_day = request.form.get('match_day', '').strip()
        match_date = request.form.get('match_date', '').strip()
        
        # Update match details
        supabase = get_supabase_client()
        
        update_data = {}
        if match_day:
            update_data["match_day"] = match_day
        if match_date:
            update_data["date"] = match_date
            
        if update_data:
            result = supabase.table("matches").update(update_data).eq("id", match_id).execute()
            
            if result and result.data:
                flash('Match details updated successfully')
            else:
                flash('No changes were made to the match')
        else:
            flash('No changes provided for the match')
            
        return redirect(url_for('match_stats', match_id=match_id))
    
    except Exception as e:
        flash(f'Error updating match details: {str(e)}')
        traceback.print_exc()
        return redirect(url_for('match_stats', match_id=match_id))

@app.route('/player_cards')
def view_player_cards():
    """
    Display the detected player cards for review
    """
    cards_dir = 'static/player_cards'
    
    # Check if directory exists
    if not os.path.exists(cards_dir):
        os.makedirs(cards_dir, exist_ok=True)
        flash('No player cards have been detected yet. Process a video first.')
        return redirect(url_for('index'))
    
    # Get all card images in the directory (excluding processed and debug images)
    card_images = []
    debug_images = []
    
    for filename in os.listdir(cards_dir):
        if filename.endswith('.jpg'):
            # Get the full path for the image
            filepath = os.path.join('player_cards', filename)
            
            # Separate debug images from card images
            if 'debug' in filename:
                debug_images.append({
                    'path': filepath,
                    'name': filename
                })
            elif 'processed' not in filename:
                # Get associated info file if it exists
                info_file = filename.replace('.jpg', '_info.txt')
                info_path = os.path.join(cards_dir, info_file)
                
                info_content = None
                if os.path.exists(info_path):
                    with open(info_path, 'r') as f:
                        info_content = f.read()
                
                # Get associated processed image if it exists
                processed_file = filename.replace('.jpg', '_processed.jpg')
                processed_path = os.path.join('player_cards', processed_file)
                
                # Add the card information
                card_images.append({
                    'path': filepath,
                    'name': filename,
                    'info': info_content,
                    'processed_path': processed_path if os.path.exists(os.path.join(cards_dir, processed_file)) else None
                })
    
    # Sort images by name for easier review
    card_images.sort(key=lambda x: x['name'])
    debug_images.sort(key=lambda x: x['name'])
    
    return render_template('player_cards.html', 
                          card_images=card_images,
                          debug_images=debug_images,
                          card_count=len(card_images),
                          debug_count=len(debug_images))

@app.route('/review_frames', methods=['GET'])
def review_frames():
    """
    Display frames with extracted player names for review before finalizing results
    """
    # Get frames and data from session
    frames = session.get('frames', [])
    home_players_by_frame = session.get('home_players_by_frame', {})
    away_players_by_frame = session.get('away_players_by_frame', {})
    home_team = session.get('home_team', '')
    away_team = session.get('away_team', '')
    match_day = session.get('match_day', '')
    
    if not frames:
        flash('No frames found for review. Please process a video first.')
        return redirect(url_for('index'))
    
    # Calculate total number of detected players for each team
    total_home_players = set()
    total_away_players = set()
    
    for frame_id, players in home_players_by_frame.items():
        for player in players:
            total_home_players.add(player)
            
    for frame_id, players in away_players_by_frame.items():
        for player in players:
            total_away_players.add(player)
    
    return render_template('review_frames.html',
                          frames=frames,
                          home_players_by_frame=home_players_by_frame,
                          away_players_by_frame=away_players_by_frame,
                          home_team=home_team,
                          away_team=away_team,
                          match_day=match_day,
                          total_home_players=list(total_home_players),
                          total_away_players=list(total_away_players),
                          total_frames=len(frames))

@app.route('/update_player_names', methods=['POST'])
def update_player_names():
    """
    Update player names based on user edits before finalizing results
    """
    # Get data from form
    updated_home_players = {}
    updated_away_players = {}
    frames = session.get('frames', [])
    
    # Process each frame
    for frame_id in frames:
        base_frame_id = os.path.basename(frame_id)
        
        # Get home players for this frame
        home_players_key = f'home_players_{base_frame_id}'
        if home_players_key in request.form:
            home_players_str = request.form[home_players_key]
            if home_players_str.strip():
                # Split by comma or newline
                home_players = [p.strip() for p in re.split(r'[,\n]', home_players_str) if p.strip()]
                updated_home_players[frame_id] = home_players
        
        # Get away players for this frame
        away_players_key = f'away_players_{base_frame_id}'
        if away_players_key in request.form:
            away_players_str = request.form[away_players_key]
            if away_players_str.strip():
                # Split by comma or newline
                away_players = [p.strip() for p in re.split(r'[,\n]', away_players_str) if p.strip()]
                updated_away_players[frame_id] = away_players
    
    # Update session with modified player names
    session['home_players_by_frame'] = updated_home_players
    session['away_players_by_frame'] = updated_away_players
    
    # Consolidate all player names for final processing
    all_home_players = []
    all_away_players = []
    
    for frame_id, players in updated_home_players.items():
        all_home_players.extend(players)
        
    for frame_id, players in updated_away_players.items():
        all_away_players.extend(players)
    
    # Remove duplicates while preserving order
    unique_home_players = list(dict.fromkeys(all_home_players))
    unique_away_players = list(dict.fromkeys(all_away_players))
    
    # Store final player lists in session
    session['home_players'] = unique_home_players
    session['away_players'] = unique_away_players
    
    # Prepare player data for display (reusing the existing function)
    home_team = session.get('home_team', '')
    away_team = session.get('away_team', '')
    match_day = session.get('match_day', '')
    
    home_data, away_data, unmatched_home, unmatched_away = prepare_player_data_for_display(
        home_team, away_team, unique_home_players, unique_away_players
    )
    
    # Store results in session
    session['results'] = {
        'home_team': home_team,
        'away_team': away_team,
        'match_day': match_day,
        'home_data': home_data,
        'away_data': away_data,
        'unmatched_home': unmatched_home,
        'unmatched_away': unmatched_away
    }
    
    flash('Player names updated successfully')
    return redirect(url_for('results'))

@app.route('/batch/review/<video_id>')
def batch_review_frames(video_id):
    """
    Display frames with extracted player names for a batch video for review
    """
    # Get the video from queue
    video = video_queue.get_video(video_id)
    
    if not video:
        flash('Video not found')
        return redirect(url_for('batch_upload'))
    
    # Get results for this video
    results = video_queue.results.get(video_id, {})
    
    if not results or 'frames' not in results:
        flash('No frame data available for this video')
        return redirect(url_for('batch_upload'))
    
    # Get frames and player data
    frames = results.get('frames', [])
    home_players_by_frame = results.get('home_players_by_frame', {})
    away_players_by_frame = results.get('away_players_by_frame', {})
    home_team = results.get('home_team', '')
    away_team = results.get('away_team', '')
    match_day = results.get('match_day', '')
    
    # Calculate total number of detected players for each team
    total_home_players = set()
    total_away_players = set()
    
    for frame_id, players in home_players_by_frame.items():
        for player in players:
            total_home_players.add(player)
            
    for frame_id, players in away_players_by_frame.items():
        for player in players:
            total_away_players.add(player)
    
    return render_template('review_frames.html',
                          frames=frames,
                          home_players_by_frame=home_players_by_frame,
                          away_players_by_frame=away_players_by_frame,
                          home_team=home_team,
                          away_team=away_team,
                          match_day=match_day,
                          total_home_players=list(total_home_players),
                          total_away_players=list(total_away_players),
                          total_frames=len(frames),
                          is_batch=True,
                          video=video,
                          video_id=video_id)

@app.route('/batch/update_player_names/<video_id>', methods=['POST'])
def batch_update_player_names(video_id):
    """
    Update player names for a batch video based on user edits
    """
    # Get the video from queue
    video = video_queue.get_video(video_id)
    
    if not video:
        flash('Video not found')
        return redirect(url_for('batch_upload'))
    
    # Get results for this video
    results = video_queue.results.get(video_id, {})
    
    if not results:
        flash('No results found for this video')
        return redirect(url_for('batch_upload'))
    
    # Get data from form
    updated_home_players = {}
    updated_away_players = {}
    frames = results.get('frames', [])
    
    # Process each frame
    for frame_id in frames:
        base_frame_id = os.path.basename(frame_id)
        
        # Get home players for this frame
        home_players_key = f'home_players_{base_frame_id}'
        if home_players_key in request.form:
            home_players_str = request.form[home_players_key]
            if home_players_str.strip():
                # Split by comma or newline
                home_players = [p.strip() for p in re.split(r'[,\n]', home_players_str) if p.strip()]
                updated_home_players[frame_id] = home_players
        
        # Get away players for this frame
        away_players_key = f'away_players_{base_frame_id}'
        if away_players_key in request.form:
            away_players_str = request.form[away_players_key]
            if away_players_str.strip():
                # Split by comma or newline
                away_players = [p.strip() for p in re.split(r'[,\n]', away_players_str) if p.strip()]
                updated_away_players[frame_id] = away_players
    
    # Update results with modified player names
    results['home_players_by_frame'] = updated_home_players
    results['away_players_by_frame'] = updated_away_players
    
    # Consolidate all player names for final processing
    all_home_players = []
    all_away_players = []
    
    for frame_id, players in updated_home_players.items():
        all_home_players.extend(players)
        
    for frame_id, players in updated_away_players.items():
        all_away_players.extend(players)
    
    # Remove duplicates while preserving order
    unique_home_players = list(dict.fromkeys(all_home_players))
    unique_away_players = list(dict.fromkeys(all_away_players))
    
    # Prepare player data for display
    home_team = results.get('home_team', '')
    away_team = results.get('away_team', '')
    match_day = results.get('match_day', '')
    
    home_data, away_data, unmatched_home, unmatched_away = prepare_player_data_for_display(
        home_team, away_team, unique_home_players, unique_away_players
    )
    
    # Update the results
    results['home_data'] = home_data
    results['away_data'] = away_data
    results['unmatched_home'] = unmatched_home
    results['unmatched_away'] = unmatched_away
    
    # Store updated results
    video_queue.results[video_id] = results
    
    flash('Player names updated successfully')
    return redirect(url_for('batch_results', video_id=video_id))

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
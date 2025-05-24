# Player Appearance Tracker

## Overview
This application is a streamlined version of the original Player Appearance Tracker. It focuses exclusively on tracking player appearances in matches without any video processing capabilities.

## Key Features
- **Player Management**: Track players and their team affiliations
- **Match Management**: Create match days and record which players appeared in matches
- **Appearance Tracking**: Manual tracking of player appearances 
- **Data Export**: Export player appearance data to Excel spreadsheets

## Removed Features
The following features have been removed from the original application:
- All video upload and processing functionality
- Frame extraction and OCR processing
- Automatic player detection from videos
- Batch video processing

## Routes
The application includes the following key routes:

### Main Pages
- `/` - Home page
- `/players` - View and filter players
- `/matches` - View all matches and create new match days
- `/match/<match_id>` - View details about a specific match
- `/match/<match_id>/edit` - Edit player appearances for a match

### API Endpoints
- `/api/teams` - Get all teams
- `/api/team/<team_id>` - Get information about a specific team
- `/match/<match_id>/update_appearances` - Update player appearances via AJAX
- `/add_unmatched_player/<match_day_id>` - Add an unmatched player
- `/edit_unmatched_player/<match_day_id>` - Edit an unmatched player
- `/delete_unmatched_player/<match_day_id>` - Delete an unmatched player
- `/match_player/<match_day_id>` - Match an unmatched player to existing player

### Data Export
- `/export/teams/excel` - Generate Excel export
- `/export/progress/<export_id>` - View export progress
- `/export/status/<export_id>` - API for export status
- `/export/download/<export_id>` - Download generated Excel file

## Installation
1. Install the required dependencies: `pip install -r new_requirements.txt`
2. Set up environment variables in a `.env` file:
   ```
   SUPABASE_URL=your_supabase_url
   SUPABASE_KEY=your_supabase_key
   SECRET_KEY=your_flask_secret_key
   ```
3. Run the application: `python new_app.py`

## Database Structure
The application uses Supabase as its backend and requires the following tables:
- `teams` - Team records
- `players` - Player records with team affiliations
- `matches` - Match day records
- `appearances` - Records of which players appeared in which matches
- `unmatched_players` - Tracking of player names that couldn't be matched 
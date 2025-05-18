# Player Appearance Tracker

A Flask web application that automatically extracts player appearances from match videos and updates a Supabase database.

## Features

- Upload match videos for automatic player appearance tracking
- Extract player names from "Player Ratings" screens in the video
- Match extracted player names with database records
- Update player appearance records in Supabase
- Track total appearances for each player
- View comprehensive match and player statistics

## Prerequisites

- Python 3.8 or higher
- Supabase project with tables for teams, players, matches, and appearances
- OCR dependencies (will be installed via requirements.txt)

## Database Structure

The application requires a Supabase project with the following tables:

1. **teams**:
   - `id` (UUID, primary key)
   - `name` (string)
   - `created_at` (timestamp)

2. **players**:
   - `id` (UUID, primary key)
   - `name` (string)
   - `team_id` (UUID, foreign key to teams)
   - `value` (string)
   - `salary` (string)
   - `total_appearances` (integer)
   - `created_at` (timestamp)

3. **matches**:
   - `id` (UUID, primary key)
   - `home_team_id` (UUID, foreign key to teams)
   - `away_team_id` (UUID, foreign key to teams)
   - `match_day` (string, e.g., "MD1")
   - `date` (timestamp)
   - `created_at` (timestamp)

4. **appearances**:
   - `id` (UUID, primary key)
   - `player_id` (UUID, foreign key to players)
   - `match_id` (UUID, foreign key to matches)
   - `created_at` (timestamp)

## Installation

1. Clone this repository:
   ```
   git clone <repository-url>
   cd player-appearance-tracker
   ```

2. Create a virtual environment and activate it:
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

4. Create a `.env` file with your Supabase credentials:
   ```
   SUPABASE_URL=https://your-project-id.supabase.co
   SUPABASE_KEY=your-api-key
   SECRET_KEY=your-flask-secret-key
   ```

## Usage

1. Start the Flask application:
   ```
   python app.py
   ```

2. Open a web browser and navigate to `http://localhost:5000`

3. Upload a match video:
   - Select the home and away teams from the dropdown menus
   - Choose the match day (MD1, MD2, etc.)
   - Select a video file that contains player ratings screens
   - Click "Upload & Process Video"

4. View results:
   - The application will extract frames from the video
   - OCR will identify player names from player ratings screens
   - Names will be matched with database records
   - Appearances will be recorded in the database
   - Total appearances for each player will be updated

## Video Requirements

For optimal results, videos should contain:
- "Player Ratings: Home" and "Player Ratings: Away" screens
- Clear, readable player names
- Naming format should be: "[HOME TEAM] VS [AWAY TEAM] MD[NUMBER].mp4"

## How It Works

1. **Video Upload**: The user uploads a video file and selects the teams and match day
2. **Frame Extraction**: OpenCV extracts frames from the video
3. **OCR Processing**: EasyOCR extracts text from frames to identify player names
4. **Name Matching**: Extracted names are matched with players in the database
5. **Database Update**: Player appearances are recorded and statistics are updated

## Acknowledgments

This project uses the following technologies:
- Flask for the web framework
- Supabase for the database backend
- OpenCV for video processing
- EasyOCR for text extraction
- Bootstrap for styling

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Deployment to Render

This application can be deployed to Render.com using GitHub integration. Follow these steps:

1. **Fork this repository to your GitHub account**

2. **Create a Render account**
   - Sign up at [render.com](https://render.com)
   - Connect your GitHub account to Render

3. **Create a new Web Service**
   - From your Render dashboard, click "New" and select "Web Service"
   - Connect your GitHub repository
   - Render will automatically detect the `render.yaml` configuration

4. **Configure environment variables**
   - In the Render dashboard for your service, go to "Environment"
   - Add the following environment variables:
     - `SUPABASE_URL`: Your Supabase project URL
     - `SUPABASE_KEY`: Your Supabase API key
   - The `SECRET_KEY` will be automatically generated

5. **Deploy**
   - Render will automatically build and deploy your application
   - Any future pushes to the main branch will trigger automatic redeployments

6. **Access your application**
   - Once deployed, you can access your application at the URL provided by Render
   - The format will be: `https://your-service-name.onrender.com`

**Note**: This application uses Render's ephemeral filesystem for temporary storage. Uploaded videos and generated frames are not persisted between deployments. 
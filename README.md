# Player Appearance Tracker

A Flask web application that automatically extracts player appearances from match videos and updates a Supabase database.

## Features

- Upload match videos for automatic player appearance tracking
- Extract player names from "Player Ratings" screens in the video
- Match extracted player names with database records
- Update player appearance records in Supabase
- Track total appearances for each player
- View comprehensive match and player statistics
- Cloud storage for videos and frames using Cloudinary

## Prerequisites

- Python 3.8 or higher
- Supabase project with tables for teams, players, matches, and appearances
- OCR dependencies (will be installed via requirements.txt)
- Cloudinary account for file storage

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

## Local Installation

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

4. Create a `.env` file with your credentials:
   ```
   SUPABASE_URL=https://your-project-id.supabase.co
   SUPABASE_KEY=your-api-key
   SECRET_KEY=your-flask-secret-key
   CLOUDINARY_CLOUD_NAME=your-cloud-name
   CLOUDINARY_API_KEY=your-api-key
   CLOUDINARY_API_SECRET=your-api-secret
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

## Deployment to Render

### Prerequisites for Deployment

1. A [GitHub](https://github.com/) account
2. A [Render](https://render.com/) account
3. A [Cloudinary](https://cloudinary.com/) account
4. A [Supabase](https://supabase.com/) project

### Step 1: Push Your Code to GitHub

1. Create a new GitHub repository
2. Initialize your local repository and push to GitHub:
   ```
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/yourusername/your-repo-name.git
   git push -u origin main
   ```

### Step 2: Set Up Cloudinary

1. Sign up for a Cloudinary account at [cloudinary.com](https://cloudinary.com/)
2. From your Cloudinary dashboard, note your:
   - Cloud name
   - API Key
   - API Secret

### Step 3: Deploy to Render

1. Log in to [Render](https://render.com/)
2. Click "New" and select "Web Service"
3. Connect your GitHub repository
4. Configure your web service:
   - **Name**: appearence-app (or your preferred name)
   - **Runtime**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`

5. Add the following environment variables:
   - `PYTHON_VERSION`: 3.9.0
   - `SUPABASE_URL`: Your Supabase URL
   - `SUPABASE_KEY`: Your Supabase API key
   - `SECRET_KEY`: A secure random string
   - `CLOUDINARY_CLOUD_NAME`: Your Cloudinary cloud name
   - `CLOUDINARY_API_KEY`: Your Cloudinary API key
   - `CLOUDINARY_API_SECRET`: Your Cloudinary API secret

6. Click "Create Web Service"

### Step 4: Automatic Deployments

Once your service is deployed, Render will automatically deploy new versions whenever you push to your GitHub repository.

## Video Requirements

For optimal results, videos should contain:
- "Player Ratings: Home" and "Player Ratings: Away" screens
- Clear, readable player names
- Naming format should be: "[HOME TEAM] VS [AWAY TEAM] MD[NUMBER].mp4"

## How It Works

1. **Video Upload**: The user uploads a video file and selects the teams and match day
2. **Cloud Storage**: Videos are stored in Cloudinary
3. **Frame Extraction**: OpenCV extracts frames from the video
4. **Frame Storage**: Extracted frames are stored in Cloudinary
5. **OCR Processing**: EasyOCR extracts text from frames to identify player names
6. **Name Matching**: Extracted names are matched with players in the database
7. **Database Update**: Player appearances are recorded and statistics are updated

## Acknowledgments

This project uses the following technologies:
- Flask for the web framework
- Supabase for the database backend
- Cloudinary for file storage
- OpenCV for video processing
- EasyOCR for text extraction
- Bootstrap for styling
- Render for hosting and deployment

## License

This project is licensed under the MIT License - see the LICENSE file for details. 
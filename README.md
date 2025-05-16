# Player Detection Application

A Flask application for detecting players in football videos, extracting their names using OCR, and managing player appearances.

## Features

- Upload and process football match videos
- Extract frames from videos
- Detect player ratings cards
- Extract player names using OCR
- Review and edit detected players
- Export player appearance data
- Batch processing capability

## Deployment on Render.com

This application is configured for easy deployment on Render.com using GitHub integration.

### Prerequisites

1. A GitHub account
2. A Cloudinary account (for file storage)
3. A Render.com account

### Deployment Steps

1. **Fork or Push this Repository to GitHub**

2. **Set Up Cloudinary Account**
   - Sign up at [Cloudinary](https://cloudinary.com)
   - Note your Cloud Name, API Key, and API Secret

3. **Connect to Render.com**
   - Sign up at [Render](https://render.com)
   - From your dashboard, click "New" and select "Blueprint"
   - Connect your GitHub account and select this repository
   - Render will detect the `render.yaml` configuration

4. **Configure Environment Variables**
   - During the setup process, provide the following environment variables:
     - `CLOUDINARY_CLOUD_NAME`: Your Cloudinary cloud name
     - `CLOUDINARY_API_KEY`: Your Cloudinary API key
     - `CLOUDINARY_API_SECRET`: Your Cloudinary API secret

5. **Deploy the Service**
   - Click "Apply" to start the deployment process
   - Render will build and deploy your application

6. **Access Your Application**
   - Once deployment is complete, you can access your application at the URL provided by Render

## Local Development

### Installation

1. Clone the repository
   ```
   git clone https://github.com/yourusername/player-detection-app.git
   cd player-detection-app
   ```

2. Install dependencies
   ```
   pip install -r requirements.txt
   ```

3. Set environment variables
   ```
   export CLOUDINARY_CLOUD_NAME=your_cloud_name
   export CLOUDINARY_API_KEY=your_api_key
   export CLOUDINARY_API_SECRET=your_api_secret
   ```

4. Run the application
   ```
   flask run
   ```

5. Access the application at `http://localhost:5000`

## Note on File Storage

This application uses Cloudinary for file storage, which makes it compatible with Render.com's ephemeral filesystem. All uploaded videos, extracted frames, and player cards are stored in Cloudinary, not on the local filesystem. 
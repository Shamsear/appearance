import os
import time
import shutil

def cleanup_old_files(uploads_folder, frames_folder, max_age_hours=24):
    """
    Clean up old files from the uploads and frames folders.
    
    Args:
        uploads_folder: Path to the uploads folder
        frames_folder: Path to the frames folder
        max_age_hours: Maximum age of files in hours before they're deleted
    
    Returns:
        tuple: (cleaned_uploads, cleaned_frames) counts of removed files
    """
    current_time = time.time()
    max_age_seconds = max_age_hours * 3600
    
    # Stats for reporting
    cleaned_uploads = 0
    cleaned_frames = 0
    
    # Clean up upload folder
    print(f"Cleaning up files in {uploads_folder} older than {max_age_hours} hours")
    for filename in os.listdir(uploads_folder):
        file_path = os.path.join(uploads_folder, filename)
        if os.path.isfile(file_path):
            file_age = current_time - os.path.getmtime(file_path)
            if file_age > max_age_seconds:
                try:
                    os.remove(file_path)
                    cleaned_uploads += 1
                    print(f"Removed old upload: {file_path}")
                except Exception as e:
                    print(f"Error removing {file_path}: {str(e)}")
    
    # Clean up frames folder
    print(f"Cleaning up session folders in {frames_folder} older than {max_age_hours} hours")
    for dirname in os.listdir(frames_folder):
        dir_path = os.path.join(frames_folder, dirname)
        if os.path.isdir(dir_path):
            # Check if any file in directory is newer than max_age
            newest_file_time = 0
            for root, _, files in os.walk(dir_path):
                for filename in files:
                    file_path = os.path.join(root, filename)
                    file_time = os.path.getmtime(file_path)
                    newest_file_time = max(newest_file_time, file_time)
            
            # If newest file is older than max_age, remove the whole directory
            dir_age = current_time - newest_file_time if newest_file_time > 0 else current_time
            if dir_age > max_age_seconds:
                try:
                    shutil.rmtree(dir_path)
                    cleaned_frames += 1
                    print(f"Removed old frame session: {dir_path}")
                except Exception as e:
                    print(f"Error removing {dir_path}: {str(e)}")
    
    return cleaned_uploads, cleaned_frames

def schedule_cleanup(app):
    """
    Schedule regular cleanup of old files
    
    Args:
        app: Flask application instance
    """
    from apscheduler.schedulers.background import BackgroundScheduler
    
    def cleanup_job():
        cleanup_old_files(
            app.config['UPLOAD_FOLDER'], 
            app.config['FRAMES_FOLDER']
        )
    
    # Create scheduler and add job
    scheduler = BackgroundScheduler()
    scheduler.add_job(cleanup_job, 'interval', hours=6)  # Run every 6 hours
    scheduler.start()
    
    # Shut down scheduler when app terminates
    import atexit
    atexit.register(lambda: scheduler.shutdown()) 
import os
import cloudinary
import cloudinary.uploader
import cloudinary.api
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure Cloudinary
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
    secure=True
)

def upload_file(file_path, folder="uploads", resource_type="auto"):
    """
    Upload a file to Cloudinary
    
    Args:
        file_path: Path to the file to upload
        folder: Folder in Cloudinary to store the file
        resource_type: Type of resource (auto, image, video, raw)
        
    Returns:
        dict: Cloudinary response with upload details
    """
    try:
        response = cloudinary.uploader.upload(
            file_path,
            folder=folder,
            resource_type=resource_type
        )
        return response
    except Exception as e:
        print(f"Error uploading to Cloudinary: {str(e)}")
        return None

def upload_image(image_data, folder="frames", resource_type="image"):
    """
    Upload an image to Cloudinary
    
    Args:
        image_data: Image data or path
        folder: Folder in Cloudinary to store the image
        resource_type: Type of resource (usually 'image')
        
    Returns:
        dict: Cloudinary response with upload details
    """
    try:
        response = cloudinary.uploader.upload(
            image_data,
            folder=folder,
            resource_type=resource_type
        )
        return response
    except Exception as e:
        print(f"Error uploading image to Cloudinary: {str(e)}")
        return None

def delete_file(public_id):
    """
    Delete a file from Cloudinary
    
    Args:
        public_id: Public ID of the file to delete
        
    Returns:
        dict: Cloudinary response with deletion details
    """
    try:
        response = cloudinary.uploader.destroy(public_id)
        return response
    except Exception as e:
        print(f"Error deleting from Cloudinary: {str(e)}")
        return None

def get_url(public_id, resource_type="image"):
    """
    Get the URL for a Cloudinary resource
    
    Args:
        public_id: Public ID of the resource
        resource_type: Type of resource (image, video, raw)
        
    Returns:
        str: URL to the resource
    """
    try:
        return cloudinary.CloudinaryImage(public_id).build_url()
    except Exception as e:
        print(f"Error generating Cloudinary URL: {str(e)}")
        return None 
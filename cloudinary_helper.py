import os
import tempfile
import cv2
import numpy as np
import urllib.request
from io import BytesIO
import cloudinary
import cloudinary.uploader
import cloudinary.api

# Configure Cloudinary
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME', 'dlof3pvkc'),
    api_key=os.environ.get('CLOUDINARY_API_KEY', '593158463978599'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET', 'fF3_VATjBf4sn0Vyf0zenWflCVo'),
    secure=True
)

def upload_file(file_path, file_content):
    """Upload a file to Cloudinary and return the URL"""
    folder = os.path.dirname(file_path)
    filename = os.path.basename(file_path)
    public_id = os.path.splitext(filename)[0]
    
    # Handle different input types
    if isinstance(file_content, str) and os.path.exists(file_content):
        # It's a local file path
        result = cloudinary.uploader.upload(
            file_content, 
            folder=folder,
            public_id=public_id,
            resource_type="auto"  # Auto-detect resource type (image, video, etc.)
        )
    else:
        # It's file content (file object or bytes)
        result = cloudinary.uploader.upload(
            file_content, 
            folder=folder,
            public_id=public_id,
            resource_type="auto"
        )
    
    return result['secure_url']

def download_file(url, local_path=None):
    """Download a file from Cloudinary to local path or memory"""
    if not url.startswith('http'):
        return url
        
    if local_path:
        # Download to file
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        urllib.request.urlretrieve(url, local_path)
        return local_path
    else:
        # Download to memory
        with urllib.request.urlopen(url) as response:
            file_obj = BytesIO(response.read())
            file_obj.seek(0)
            return file_obj

def get_image_as_array(url):
    """Get an image from Cloudinary as a numpy array for OpenCV"""
    if not url.startswith('http'):
        # It's a local path
        return cv2.imread(url)
        
    # Download to memory
    try:
        file_obj = download_file(url)
        file_bytes = np.asarray(bytearray(file_obj.read()), dtype=np.uint8)
        return cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    except Exception as e:
        print(f"Error loading image from URL: {e}")
        return None

def save_cv2_image(image, file_path):
    """Save an OpenCV image to Cloudinary"""
    # Save to temporary file first
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp:
        temp_path = temp.name
    
    cv2.imwrite(temp_path, image)
    
    try:
        # Upload to Cloudinary
        url = upload_file(file_path, temp_path)
        return url
    finally:
        # Clean up temporary file
        if os.path.exists(temp_path):
            os.unlink(temp_path)

def extract_cloudinary_id(url):
    """Extract the Cloudinary ID from a URL"""
    if not url.startswith('http'):
        return url
        
    # Example URL: https://res.cloudinary.com/dlof3pvkc/image/upload/v1623456789/frames/frame_123.jpg
    parts = url.split('/')
    if len(parts) >= 7:
        # Remove version number and return the rest
        path = '/'.join(parts[6:])
        return path
    return url 
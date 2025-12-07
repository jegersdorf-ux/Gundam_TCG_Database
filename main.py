import json
import os
import random
import datetime
import cloudinary
import cloudinary.uploader

# --- CONFIGURATION ---
# We use os.getenv so we don't leak secrets in the code
cloudinary.config(
  cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME'),
  api_key = os.getenv('CLOUDINARY_API_KEY'),
  api_secret = os.getenv('CLOUDINARY_API_SECRET'),
  secure = True
)

# --- STEP 1: UPDATE IMAGE ---
# specific_public_id keeps the URL constant. 
# e.g., if ID is "daily_chart", URL is always .../daily_chart.png
def update_image():
    # In reality, you would generate a chart or download an image here.
    # For this demo, we assume you have a file called 'chart.png' ready.
    # If you don't have one, the script will crash, so ensure logic creates one.
    
    # Example: uploading a local file
    if os.path.exists("chart.png"):
        print("Uploading image...")
        upload_result = cloudinary.uploader.upload(
            "chart.png",
            public_id = "daily_chart", 
            unique_filename = False, 
            overwrite = True,
            invalidate = True # Refreshes the CDN cache
        )
        return upload_result['secure_url']
    else:
        print("No image found to upload.")
        return None

# --- STEP 2: UPDATE DATA ---
def update_json(image_url):
    data = {
        "last_updated": str(datetime.datetime.now()),
        "status": "active",
        "value": random.randint(100, 500), # Replace with your real scraping logic
        "image_url": image_url or "No image uploaded"
    }
    
    # Save to file
    with open("data.json", "w") as f:
        json.dump(data, f, indent=2)
    print("JSON updated.")

# --- EXECUTION ---
if __name__ == "__main__":
    # 1. Run your logic to generate the 'chart.png' here if needed
    
    # 2. Upload to cloud
    url = update_image()
    
    # 3. Save text data
    update_json(url)
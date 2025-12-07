import json
import os
import datetime
import requests # Used to fetch data from websites
import cloudinary
import cloudinary.uploader

# --- CONFIGURATION ---
# 1. Cloudinary Setup (Reads from GitHub Secrets)
cloudinary.config(
  cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME'),
  api_key = os.getenv('CLOUDINARY_API_KEY'),
  api_secret = os.getenv('CLOUDINARY_API_SECRET'),
  secure = True
)

# --- HELPER: Download Image ---
# Downloads an image from a URL to a local file so we can upload it to Cloudinary
def download_image_from_web(image_url, filename="temp_image.png"):
    try:
        response = requests.get(image_url, stream=True)
        if response.status_code == 200:
            with open(filename, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            return filename
    except Exception as e:
        print(f"Error downloading image: {e}")
    return None

# --- STEP 1: YOUR SCRAPING LOGIC ---
def fetch_gundam_data():
    print("Fetching data...")
    
    # =====================================================
    # PASTE YOUR REAL SCRAPING CODE HERE
    # =====================================================
    
    # EXAMPLE: Let's pretend we fetched this from a TCG website
    # In reality, you might use requests.get() and BeautifulSoup here.
    
    scraped_data = {
        "card_name": "Gundam Barbatos",
        "price": 45.50, # Replace with real variable
        "stock": "In Stock",
        # This URL would usually come from the site you are scraping
        "source_image_url": "https://upload.wikimedia.org/wikipedia/commons/a/a3/Eq_it-na_pizza-margherita_sep2005_sml.jpg" 
    }
    
    return scraped_data

# --- STEP 2: CLOUDINARY UPLOAD ---
def process_images(data):
    # Check if we have an image to upload
    if "source_image_url" in data:
        print(f"Found image URL: {data['source_image_url']}")
        
        # 1. Download it locally first
        local_file = download_image_from_web(data['source_image_url'])
        
        if local_file:
            print("Uploading to Cloudinary...")
            # 2. Upload to Cloudinary
            # public_id="latest_card" keeps the URL constant!
            upload_result = cloudinary.uploader.upload(
                local_file,
                public_id = "latest_card_image", 
                unique_filename = False, 
                overwrite = True,
                invalidate = True
            )
            
            # 3. Clean up local file
            os.remove(local_file)
            
            # 4. Return the new Cloudinary URL
            return upload_result['secure_url']
            
    return None

# --- STEP 3: SAVE JSON ---
def save_database(data, cloud_image_url):
    final_record = {
        "last_updated": str(datetime.datetime.now()),
        "card_name": data['card_name'],
        "price": data['price'],
        "status": data['stock'],
        "image_url": cloud_image_url or "No Image Available"
    }
    
    # Update data.json
    with open("data.json", "w") as f:
        json.dump(final_record, f, indent=2)
    print("Database saved to data.json")

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    # 1. Get the data
    raw_data = fetch_gundam_data()
    
    # 2. Handle the image
    new_image_url = process_images(raw_data)
    
    # 3. Save everything
    save_database(raw_data, new_image_url)

import requests
import json
import os
import time
import datetime
import cloudinary
import cloudinary.uploader

# --- CONFIGURATION ---
API_URL = "https://exburst.dev/gundam/external/fetch_data.php?gameid=gundam&series=*&seriesColumn=series"
JSON_FILE = "data.json" 

# Cloudinary Setup
cloudinary.config(
  cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME'),
  api_key = os.getenv('CLOUDINARY_API_KEY'),
  api_secret = os.getenv('CLOUDINARY_API_SECRET'),
  secure = True
)

# --- HEADERS ---
HEADERS = {
    'accept': '*/*',
    'accept-language': 'en-US,en;q=0.9',
    'priority': 'u=1, i',
    'referer': 'https://exburst.dev/gundam/cardlist',
    'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36'
}

# Triple-quoted cookie string to prevent syntax errors
COOKIE_STRING = """_pubcid=0cc16541-a962-465a-a373-d8222150644e; _pubcid_cst=znv0HA%3D%3D; _lr_env_src_ats=false; _nitroID=8a1c178f6dfaf51816294fe4c864fbe9; ncmp.domain=exburst.dev; nitro-uid=%7B%22TDID%22%3A%2205580ac1-7179-4436-b8c7-fc7641f217b6%22%2C%22TDID_LOOKUP%22%3A%22TRUE%22%2C%22TDID_CREATED_AT%22%3A%222025-10-06T05%3A36%3A48%22%7D; nitro-uid_cst=znv0HA%3D%3D; _lr_geo_location_state=FL; _lr_geo_location=US; _au_1d=AU1D-0100-001762407409-33ZDD7OS-IDUF; _cc_id=9b79e59f3eb2da79722329635e945fdf; panoramaId_expiry=1763012209469; panoramaId=1e7661846f78f16da448bd0504a3185ca02c67d16040a9ab7ab079adfb3ce5a1; panoramaIdType=panoDevice; PHPSESSID=4d6b253f23abc12017ba05ae523505a5; _ga=GA1.1.1401858402.1762407411; _lr_sampling_rate=100; _lr_retry_request=true; __gads=ID=be3d6323af3fd86c:T=1762407412:RT=1762415092:S=ALNI_MZJiA4NzkNEFyjbo4vjeKbFEEpkKg; __gpi=UID=00001308ab757751:T=1762407412:RT=1762415092:S=ALNI_MYwdXfbIULSCw0WDsKHkniGvTgs7g; __eoi=ID=08d4cbea426e167f:T=1762407412:RT=1762415092:S=AA-AfjYGLqJ5d68_vo_dZuRTZqyX; TAPAD=%7B%22id%22%3A%2241875828-6d3c-4996-9bc0-bf7884bcac3d%22%7D; _ga__FVWZ0RM4DH=GS2.1.s1762415154$o3$g0$t1762415154$j60$l0$h0; _ga_13BZTMMGC0=GS2.1.s1762415092$o3$g0$t1762415154$j60$l0$h0; cto_bundle=ylAy3F9ONzhaajE0Z2tZbXo5dzJJZXVqQmZ3dzZEdlBxJTJGMm41bTVkbXBJTUF2Y3ZMd2hzMWJPVWV5SXNlZlR0YmIxRWh3ZSUyRkVySkU0T09lbFlqZG5wV3FlJTJCR2YwaXVjVzNkVlRxJTJCSzNsQU1HSG9IZkRsRnBzeSUyQmQlMkJtMzZtU29qcmdLUVpDcWQ3ZUNMTWhweGVqMTBOaUluVWclM0QlM0Q; cto_bidid=drX6z18zY3IwcFNjNjklMkJSJTJCdGRKeXU2VzBhMFZVRWh6VlhQZkZmeWZCMFpLTnVjSlZsNTFlVHo0NDcwZVpoSDglMkZJbF1qODhydVJOTUY1M3JLOXlodmVEelJhWlBhR1B5bFBwRjR5R05HRXN1VEs4VSUzRA"""

def parse_cookie_string(cookie_string):
    cookies = {}
    clean_cookie = cookie_string.replace('\n', '')
    for cookie in clean_cookie.strip().split('; '):
        try:
            name, value = cookie.split('=', 1)
            cookies[name] = value
        except ValueError:
            pass
    return cookies

def upload_image_to_cloudinary(session, image_url, card_id):
    temp_filename = f"temp_{card_id}.jpg"
    try:
        with session.get(image_url, stream=True) as r:
            r.raise_for_status()
            with open(temp_filename, 'wb') as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
        
        print(f"Uploading image for {card_id}...")
        upload_result = cloudinary.uploader.upload(
            temp_filename,
            public_id = f"gundam_cards/{card_id}", 
            unique_filename = False, 
            overwrite = True,
            invalidate = True
        )
        if os.path.exists(temp_filename):
            os.remove(temp_filename)
        return upload_result['secure_url']
    except Exception as e:
        print(f"Failed to upload image for {card_id}: {e}")
        if os.path.exists(temp_filename):
            os.remove(temp_filename)
        return None

def run_update():
    session = requests.Session()
    session.headers.update(HEADERS)
    session.cookies.update(parse_cookie_string(COOKIE_STRING))

    # 1. Load Existing DB
    if os.path.exists(JSON_FILE):
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            try:
                raw_list = json.load(f)
                existing_db = {item['card_id']: item for item in raw_list}
            except json.JSONDecodeError:
                existing_db = {}
    else:
        existing_db = {}

    print(f"Loaded {len(existing_db)} existing cards.")

    # 2. Fetch Data
    print(f"Querying API: {API_URL}")
    try:
        response = session.get(API_URL)
        response.raise_for_status()
        api_data = response.json()
    except Exception as e:
        print(f"CRITICAL ERROR: Could not fetch API data. {e}")
        return

    print(f"API returned {len(api_data)} cards.")
    updates_count = 0
    
    # 3. Process Cards (THE CATCH-ALL STRATEGY)
    for card in api_data:
        card_id = card.get('cardNo')
        original_image_url = card.get('image')
        
        if not card_id or not original_image_url:
            continue

        is_new_card = card_id not in existing_db
        has_valid_image = False
        if not is_new_card:
            current_entry = existing_db[card_id]
            if "cloudinary_url" in current_entry and "res.cloudinary.com" in current_entry["cloudinary_url"]:
                has_valid_image = True
        
        if is_new_card or not has_valid_image:
            print(f"Processing NEW/UPDATED card: {card_id}")
            cloud_url = upload_image_to_cloudinary(session, original_image_url, card_id)
            
            if cloud_url:
                # --- STRATEGY: START WITH EVERYTHING ---
                clean_record = card.copy() 
                
                # --- NORMALIZE CRITICAL FIELDS FOR APP ---
                clean_record["card_id"] = card_id
                clean_record["cloudinary_url"] = cloud_url
                clean_record["last_updated"] = str(datetime.datetime.now())

                # --- ENSURE COMPATIBILITY ---
                # We also explicitly map the fields our App *currently* expects
                # so we don't break the existing Seeder.
                clean_record["set"] = card.get('series', 'Unknown')
                clean_record["text"] = card.get('effect') or card.get('text', '')
                clean_record["power"] = card.get('bp') or card.get('power', 0)
                clean_record["type"] = card.get('cardType', 'Unit')
                
                existing_db[card_id] = clean_record
                updates_count += 1
                time.sleep(0.5)

    if updates_count > 0:
        print(f"Saving {updates_count} new updates...")
        final_list = list(existing_db.values())
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(final_list, f, indent=2, ensure_ascii=False)
    else:
        print("No new cards found.")

if __name__ == "__main__":
    run_update()

import requests
from bs4 import BeautifulSoup
import json
import os
import time
import datetime
import cloudinary
import cloudinary.uploader
import cloudinary.api
import re

# --- CONFIGURATION ---
DETAIL_URL_TEMPLATE = "https://www.gundam-gcg.com/en/cards/detail.php?detailSearch={}"
IMAGE_URL_TEMPLATE = "https://www.gundam-gcg.com/en/images/cards/card/{}.webp?251120"
JSON_FILE = "cards.json" 

# Cloudinary Setup
cloudinary.config(
  cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME'),
  api_key = os.getenv('CLOUDINARY_API_KEY'),
  api_secret = os.getenv('CLOUDINARY_API_SECRET'),
  secure = True
)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# GLOBAL STATE FOR RATE LIMITING
RATE_LIMIT_HIT = False

def upload_image_to_cloudinary(image_url, public_id):
    global RATE_LIMIT_HIT
    if RATE_LIMIT_HIT: return image_url

    try:
        result = cloudinary.uploader.upload(
            image_url,
            public_id=f"gundam_cards/{public_id}",
            unique_filename=False,
            overwrite=True
        )
        return result['secure_url'] 
    except Exception as e:
        error_msg = str(e)
        if "420" in error_msg or "Rate Limit" in error_msg:
            print(f"   🛑 RATE LIMIT REACHED. Switching to text-only mode.")
            RATE_LIMIT_HIT = True
        else:
            print(f"   ❌ Cloudinary Error ({public_id}): {e}")
        return image_url 

def discover_sets():
    print("🔍 Probing for sets...")
    found_sets = []
    prefixes = ["ST", "GD", "PR", "UT"] 
    
    for prefix in prefixes:
        print(f"   Checking {prefix} series...", end="")
        set_miss_streak = 0
        for i in range(1, 20): 
            set_code = f"{prefix}{i:02d}" 
            test_card = f"{set_code}-001"
            url = DETAIL_URL_TEMPLATE.format(test_card)
            
            exists = False
            try:
                resp = requests.get(url, headers=HEADERS, timeout=3)
                if resp.status_code == 200 and "cardlist" not in resp.url:
                    soup = BeautifulSoup(resp.content, "html.parser")
                    if soup.select_one(".cardName, h1"):
                        exists = True
            except: pass

            if exists:
                limit = 135 if prefix == "GD" else 35
                found_sets.append({"code": set_code, "limit": limit})
                set_miss_streak = 0
            else:
                set_miss_streak += 1
                if set_miss_streak >= 2: break 
        print(" Done.")
                
    if not found_sets:
        return [{"code": "ST01", "limit": 25}, {"code": "GD01", "limit": 105}, {"code": "GD02", "limit": 105}]
    return found_sets

def scrape_card(card_id, existing_card=None):
    """
    Scrapes data. 
    If existing_card is provided and has a valid image, we SKIP the image upload 
    to preserve bandwidth/API limits, but we still refresh all text data.
    """
    url = DETAIL_URL_TEMPLATE.format(card_id)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=5)
        if resp.status_code != 200 or "cardlist" in resp.url: return None 
        
        soup = BeautifulSoup(resp.content, "html.parser")
        
        name_tag = soup.select_one(".cardName, h1")
        if not name_tag: return None
        name = name_tag.text.strip()
        if not name: return None

        # --- Data Extraction ---
        stats = {
            "level": "-", "cost": "-", "hp": "-", "ap": "-", "rarity": "-", 
            "color": "N/A", "type": "UNIT", "zone": "-", "trait": "-", 
            "link": "-", "source": "-", "release": "-"
        }

        for dt in soup.find_all("dt"):
            label = dt.text.strip().lower()
            val_tag = dt.find_next_sibling("dd")
            if not val_tag: continue
            val = val_tag.text.strip()

            if "lv" in label: stats["level"] = val
            elif "cost" in label: stats["cost"] = val
            elif "hp" in label: stats["hp"] = val
            elif "ap" in label or "atk" in label: stats["ap"] = val
            elif "rarity" in label: stats["rarity"] = val
            elif "color" in label: stats["color"] = val
            elif "type" in label: stats["type"] = val
            elif "zone" in label: stats["zone"] = val
            elif "trait" in label: stats["trait"] = val
            elif "link" in label: stats["link"] = val
            elif "source" in label: stats["source"] = val
            elif "where" in label: stats["release"] = val

        block_icon_tag = soup.select_one(".blockIcon")
        block_icon = block_icon_tag.text.strip() if block_icon_tag else "-"

        effect_tag = soup.select_one(".cardDataRow.overview .dataTxt")
        effect_text = effect_tag.text.strip().replace("<br>", "\n") if effect_tag else ""
        
        traits = stats["trait"]

        # --- SMART IMAGE HANDLING ---
        # Logic: If we have an existing card with a Cloudinary URL, keep it.
        # Otherwise, upload.
        final_image_url = ""
        
        has_valid_existing_image = (
            existing_card 
            and "image" in existing_card 
            and "cloudinary.com" in existing_card["image"]
        )

        if has_valid_existing_image:
            final_image_url = existing_card["image"]
            # print(f"   Using existing image for {card_id}") # Optional debug
        else:
            # Only upload if we don't have it or it's not hosted by us
            official_img_url = IMAGE_URL_TEMPLATE.format(card_id)
            final_image_url = upload_image_to_cloudinary(official_img_url, card_id)

        # Construct new object
        new_data = {
            "cardNo": card_id,
            "originalId": card_id,
            "name": name,
            "series": card_id.split("-")[0],
            "cost": int(stats["cost"]) if stats["cost"].isdigit() else 0,
            "color": stats["color"],
            "rarity": stats["rarity"],
            "apData": stats["ap"],
            "effectData": effect_text,
            "categoryData": stats["type"],
            "image": final_image_url,
            "metadata": json.dumps({ 
                "level": stats["level"],
                "hp": stats["hp"],
                "def": stats["hp"],
                "atk": stats["ap"],
                "trait": traits,
                "type": stats["type"],
                "zone": stats["zone"],
                "link": stats["link"],
                "block_icon": block_icon,
                "source_title": stats["source"],
                "release_pack": stats["release"],
                "variants": [] 
            }, sort_keys=True), # Sort keys ensures consistent string comparison
            "last_updated": str(datetime.datetime.now())
        }
        return new_data

    except Exception as e:
        print(f"   ❌ Error {card_id}: {e}")
        return None

def save_db(db):
    if len(db) > 0:
        data_list = list(db.values())
        print(f"   💾 Checkpoint: Saving {len(data_list)} total cards...")
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(data_list, f, indent=2, ensure_ascii=False)

def clean_database(db):
    print("🧹 Cleaning database integrity...")
    initial_count = len(db)
    clean_db = {}
    for key, card in db.items():
        if not isinstance(card, dict): continue
        if not card.get('cardNo'): continue
        if not card.get('name'): continue
        if len(card['name'].strip()) == 0: continue
        clean_db[key] = card
    
    removed = initial_count - len(clean_db)
    if removed > 0:
        print(f"   🗑️ Removed {removed} empty/corrupted records.")
        save_db(clean_db)
    else:
        print("   ✨ Database is clean.")
    return clean_db

def has_changed(old, new):
    """
    Compares two card objects excluding timestamp fields.
    Returns True if meaningful data changed.
    """
    if not old: return True
    
    o = old.copy()
    n = new.copy()
    
    # Remove volatile fields
    o.pop('last_updated', None)
    n.pop('last_updated', None)
    
    # Compare
    return o != n

def run_update():
    master_db = {}
    if os.path.exists(JSON_FILE):
        print(f"📂 Loading existing {JSON_FILE}...")
        try:
            with open(JSON_FILE, 'r', encoding='utf-8') as f:
                data_list = json.load(f)
                for c in data_list:
                    master_db[c['cardNo']] = c
        except:
            print("   ⚠️ Error reading existing JSON. Starting fresh.")
    
    master_db = clean_database(master_db)
    sets = discover_sets()
    
    print(f"\n--- STARTING AUDIT & SCRAPE ---")
    
    for set_info in sets:
        code = set_info['code']
        limit = set_info['limit']
        print(f"\nProcessing Set: {code}...")
        
        miss_streak = 0
        max_misses = 3
        
        for i in range(1, limit + 1):
            card_id = f"{code}-{i:03d}"
            
            # Retrieve existing data (if any)
            existing_card = master_db.get(card_id)
            
            # Scrape FRESH data, passing existing card for image logic
            new_card_data = scrape_card(card_id, existing_card=existing_card)
            
            if new_card_data:
                # Check for differences
                if has_changed(existing_card, new_card_data):
                    if existing_card:
                        print(f"   📝 UPDATE detected for {card_id}")
                    else:
                        print(f"   ✅ NEW card found: {card_id}")
                        
                    master_db[card_id] = new_card_data
                else:
                    # Optional: Print a dot to show aliveness without spamming
                    # print(".", end="", flush=True)
                    pass

                miss_streak = 0
            else:
                miss_streak += 1
                if miss_streak <= max_misses:
                    print(f"   . {card_id} not found")
            
            time.sleep(0.1) 
        
        save_db(master_db)

    print("\n✅ Update Complete.")

if __name__ == "__main__":
    run_update()

import requests
from requests.exceptions import Timeout, ConnectionError, RequestException
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
FULL_CHECK = True  # True = Audit all cards. False = Only find new cards.

# URL Templates
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

RATE_LIMIT_HIT = False

def safe_int(val):
    """
    Architectural Enforcer: Ensures DB columns designed for Integers
    never receive garbage strings. Handles '+1', 'HP: 500', etc.
    """
    if not val: return 0
    try:
        # 1. Remove non-numeric characters (except minus sign for negative modifiers if any)
        clean_val = re.sub(r'[^\d-]', '', str(val))
        if not clean_val: return 0
        return int(clean_val)
    except:
        return 0

def upload_image_to_cloudinary(image_url, public_id):
    """
    Optimizes asset delivery by shifting hosting to Cloudinary CDN.
    """
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
            print(f"    🛑 RATE LIMIT REACHED. Switching to pass-through mode.")
            RATE_LIMIT_HIT = True
        # Fail gracefully: return original URL if upload fails
        return image_url

def discover_sets():
    """
    Dynamically probes the endpoint to discover active card sets.
    """
    print("🔍 Probing for sets...")
    found_sets = []
    prefixes = ["ST", "GD", "PR", "UT"]
    PROBE_TIMEOUT = 5
    
    for prefix in prefixes:
        print(f"    Checking {prefix} series...", end="")
        set_miss_streak = 0
        
        for i in range(1, 20):
            set_code = f"{prefix}{i:02d}"
            test_card = f"{set_code}-001"
            url = DETAIL_URL_TEMPLATE.format(test_card)
            
            exists = False
            try:
                resp = requests.get(url, headers=HEADERS, timeout=PROBE_TIMEOUT) 
                
                if resp.status_code == 200 and "cardlist" not in resp.url:
                    soup = BeautifulSoup(resp.content, "html.parser")
                    if soup.select_one(".cardName, h1"):
                        exists = True
            except (Timeout, ConnectionError, RequestException) as e:
                print(f"\n    ⚠️ Connection issue during probe {test_card}: {e}", end="")
                pass 
            except Exception as e:
                print(f"\n    ❌ Unexpected error during probe {test_card}: {e}", end="")
                pass

            if exists:
                limit = 135 if prefix == "GD" else 35 
                found_sets.append({"code": set_code, "limit": limit})
                set_miss_streak = 0
            else:
                set_miss_streak += 1
                if set_miss_streak >= 2: 
                    break 
        print(" Done.")
            
    if not found_sets:
        print("    No sets discovered. Using hardcoded fallback sets.")
        return [{"code": "ST01", "limit": 25}, {"code": "GD01", "limit": 105}, {"code": "GD02", "limit": 105}]
    return found_sets

def scrape_card(card_id, existing_card=None):
    url = DETAIL_URL_TEMPLATE.format(card_id)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10) 
        
        if resp.status_code != 200 or "cardlist" in resp.url: return None
        
        soup = BeautifulSoup(resp.content, "html.parser")
        
        name_tag = soup.select_one(".cardName, h1")
        if not name_tag: return None
        name = name_tag.text.strip()
        if not name: return None

        # --- Data Extraction ---
        # We default to harmless values so DB insertion doesn't fail
        raw_stats = {
            "level": "0", "cost": "0", "hp": "0", "ap": "0", "rarity": "-", 
            "color": "N/A", "type": "UNIT", "zone": "-", "trait": "-", 
            "link": "-", "source": "-", "release": "-"
        }

        # 1. Standard Description List Parsing
        for dt in soup.find_all("dt"):
            label = dt.text.strip().lower()
            val_tag = dt.find_next_sibling("dd")
            if not val_tag: continue
            val = val_tag.text.strip()

            if "lv" in label: raw_stats["level"] = val
            elif "cost" in label: raw_stats["cost"] = val
            elif "hp" in label: raw_stats["hp"] = val
            elif "ap" in label or "atk" in label: raw_stats["ap"] = val
            elif "color" in label: raw_stats["color"] = val
            elif "type" in label: raw_stats["type"] = val
            elif "zone" in label: raw_stats["zone"] = val
            elif "trait" in label: raw_stats["trait"] = val
            elif "link" in label: raw_stats["link"] = val
            elif "source" in label: raw_stats["source"] = val
            elif "where" in label: raw_stats["release"] = val

        # 2. Specific Rarity Extraction (The Fix)
        # We prioritize the dedicated class extraction over the generic list
        rarity_tag = soup.select_one(".rarity")
        if rarity_tag:
             raw_stats["rarity"] = rarity_tag.text.strip()
        elif "rarity" not in raw_stats or raw_stats["rarity"] == "-":
             # Fallback: sometimes rarity is in the DT list, but usually it's in the div
             pass

        block_icon_tag = soup.select_one(".blockIcon")
        block_icon = safe_int(block_icon_tag.text.strip()) if block_icon_tag else 0

        effect_tag = soup.select_one(".cardDataRow.overview .dataTxt")
        effect_text = effect_tag.text.strip().replace("<br>", "\n") if effect_tag else ""
        
        # --- SMART IMAGE HANDLING ---
        final_image_url = ""
        # Check if we already have a Cloudinary URL to avoid re-uploading
        has_valid_existing = (
            existing_card 
            and "image_url" in existing_card 
            and "cloudinary.com" in existing_card["image_url"]
        )

        if has_valid_existing:
            final_image_url = existing_card["image_url"]
        else:
            official_img_url = IMAGE_URL_TEMPLATE.format(card_id)
            final_image_url = upload_image_to_cloudinary(official_img_url, card_id)

        # --- THE FLATTENED WATERMELON DB SCHEMA ---
        return {
            "id": card_id,               # Primary Key
            "card_no": card_id,          # Indexed search field
            "name": name,
            "series": card_id.split("-")[0],
            "cost": safe_int(raw_stats["cost"]),
            "hp": safe_int(raw_stats["hp"]),
            "ap": safe_int(raw_stats["ap"]),
            "level": safe_int(raw_stats["level"]),
            "color": raw_stats["color"],
            "rarity": raw_stats["rarity"],
            "type": raw_stats["type"],
            "block_icon": block_icon, 
            "trait": raw_stats["trait"],        
            "zone": raw_stats["zone"],
            "link": raw_stats["link"],
            "effect_text": effect_text,
            "source_title": raw_stats["source"],
            "image_url": final_image_url,
            "release_pack": raw_stats["release"],
            # Unix Timestamp for high-performance sorting/syncing
            "last_updated": int(time.time()) 
        }

    except (Timeout, ConnectionError, RequestException) as e:
        print(f"    ❌ Error {card_id}: Request failed: {e}")
        return None
    except Exception as e:
        print(f"    ❌ Error {card_id}: Unexpected Scraping Error: {e}")
        return None

def save_db(db):
    if len(db) > 0:
        data_list = list(db.values())
        print(f"    💾 Checkpoint: Saving {len(data_list)} total cards...")
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(data_list, f, indent=2, ensure_ascii=False)

def clean_database(db):
    print("🧹 Cleaning database integrity...")
    clean_db = {}
    for key, card in db.items():
        if not isinstance(card, dict): continue
        # Normalize key lookup
        key = card.get('id') or card.get('cardNo') or card.get('card_no')
        if not key: continue
        clean_db[key] = card
    return clean_db

def has_changed(old, new):
    if not old: return True
    o = old.copy()
    n = new.copy()
    # Ignore timestamp when comparing content changes
    o.pop('last_updated', None)
    n.pop('last_updated', None)
    
    return str(o) != str(n)

def run_update():
    master_db = {}
    if os.path.exists(JSON_FILE):
        print(f"📂 Loading existing {JSON_FILE}...")
        try:
            with open(JSON_FILE, 'r', encoding='utf-8') as f:
                data_list = json.load(f)
                for c in data_list:
                    # Support legacy keys during migration
                    key = c.get('id', c.get('cardNo'))
                    if key: master_db[key] = c
        except:
            print("    ⚠️ Error reading existing JSON. Starting fresh.")
    
    master_db = clean_database(master_db)
    
    if not all([os.getenv('CLOUDINARY_CLOUD_NAME'), os.getenv('CLOUDINARY_API_KEY'), os.getenv('CLOUDINARY_API_SECRET')]):
        print("\n    🛑 WARNING: Cloudinary environment variables are missing. Image uploads will be skipped.")

    sets = discover_sets()
    
    mode_label = "DEEP AUDIT" if FULL_CHECK else "INCREMENTAL UPDATE"
    print(f"\n--- STARTING {mode_label} ---")
    
    for set_info in sets:
        code = set_info['code']
        limit = set_info['limit']
        print(f"\nProcessing Set: {code} (up to {limit} cards)...")
        
        miss_streak = 0
        max_misses = 3
        
        for i in range(1, limit + 1):
            card_id = f"{code}-{i:03d}"
            
            if not FULL_CHECK and card_id in master_db:
                miss_streak = 0
                continue
                
            existing_card = master_db.get(card_id)
            new_card_data = scrape_card(card_id, existing_card=existing_card)
            
            if new_card_data:
                if has_changed(existing_card, new_card_data):
                    status = "UPDATE" if existing_card else "NEW"
                    print(f"    📝 {status}: {card_id}")     
                    master_db[card_id] = new_card_data
                miss_streak = 0
            else:
                miss_streak += 1
                if miss_streak <= max_misses:
                    print(f"    . {card_id} not found (Miss {miss_streak}/{max_misses})")
            
            time.sleep(0.1) 
            
            if i % 200 == 0:
                 save_db(master_db) 
                 
        save_db(master_db)

    print("\n✅ Update Complete.")

if __name__ == "__main__":
    run_update()

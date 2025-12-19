import requests
from requests.exceptions import Timeout, ConnectionError, RequestException
from bs4 import BeautifulSoup
import json
import os
import time
import re
import cloudinary
import cloudinary.uploader
import cloudinary.api

# --- CONFIGURATION ---
FULL_CHECK = False 
MAX_MISSES = 3  # The "3 Strikes" Rule

# Output Files
JSON_FILE = "cards.json"
DECKS_FILE = "decks.json"
METADATA_FILE = "deck_metadata.json"

# URLs
DETAIL_URL_TEMPLATE = "https://www.gundam-gcg.com/en/cards/detail.php?detailSearch={}"
IMAGE_URL_TEMPLATE = "https://www.gundam-gcg.com/en/images/cards/card/{}.webp"
PRODUCT_URL_TEMPLATE = "https://www.gundam-gcg.com/en/products/{}.html"
LAUNCH_NEWS_URL = "https://www.gundam-gcg.com/en/news/02_82.html"

# KNOWN SETS
KNOWN_SET_PREFIXES = ["ST", "GD", "PR", "UT", "EXRP", "EXB", "EXR", "EXBP"]

# SAFETY NET: Verified Lists for ST01-ST04
SEED_DECKS = {
    "ST01": {
        "ST01-001": 2, "ST01-002": 4, "ST01-003": 4, "ST01-004": 2, "ST01-005": 4, "ST01-006": 2, "ST01-007": 4, "ST01-008": 2, "ST01-009": 4, "ST01-010": 4, "ST01-011": 4, "ST01-012": 4, "ST01-013": 2, "ST01-014": 4, "ST01-015": 2, "ST01-016": 2
    },
    "ST02": {
        "ST02-001": 2, "ST02-002": 4, "ST02-003": 4, "ST02-004": 2, "ST02-005": 4, "ST02-006": 2, "ST02-007": 4, "ST02-008": 2, "ST02-009": 4, "ST02-010": 4, "ST02-011": 4, "ST02-012": 4, "ST02-013": 2, "ST02-014": 4, "ST02-015": 2, "ST02-016": 2
    },
    "ST03": {
        "ST03-001": 2, "ST03-002": 4, "ST03-003": 4, "ST03-004": 4, "ST03-005": 2, "ST03-006": 2, "ST03-007": 4, "ST03-008": 4, "ST03-009": 2, "ST03-010": 4, "ST03-011": 4, "ST03-012": 4, "ST03-013": 2, "ST03-014": 4, "ST03-015": 2, "ST03-016": 2
    },
    "ST04": {
        "ST04-001": 2, "ST04-002": 4, "ST04-003": 4, "ST04-004": 2, "ST04-005": 4, "ST04-006": 2, "ST04-007": 4, "ST04-008": 2, "ST04-009": 4, "ST04-010": 4, "ST04-011": 4, "ST04-012": 4, "ST04-013": 2, "ST04-014": 4, "ST04-015": 2, "ST04-016": 2
    }
}

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

# --- UTILITY FUNCTIONS ---

def safe_int(val):
    if not val: return 0
    try:
        clean_val = re.sub(r'[^\d-]', '', str(val))
        if not clean_val: return 0
        return int(clean_val)
    except:
        return 0

def has_changed(old, new):
    if not old: return True
    o = old.copy()
    n = new.copy()
    o.pop('last_updated', None)
    n.pop('last_updated', None)
    return json.dumps(o, sort_keys=True) != json.dumps(n, sort_keys=True)

def check_url_exists(url):
    """Checks if a URL exists (Status 200) without downloading the content."""
    try:
        resp = requests.head(url, headers=HEADERS, timeout=3)
        return resp.status_code == 200
    except:
        return False

def extract_rarities(rarity_text):
    """
    Splits rarity string into a clean list based on ALL common delimiters found on Gundam sites.
    Input: "R・R+"      -> Output: ['R', 'R+']
    Input: "LR/LR+/LR++" -> Output: ['LR', 'LR+', 'LR++']
    Input: "C.C+"        -> Output: ['C', 'C+']
    """
    if not rarity_text: return ["-"]
    # Split by: dot (.), slash (/), comma (,), pipe (|), Japanese dot (・)
    parts = re.split(r'[・/,\.\|\u30FB]', rarity_text) 
    return [p.strip() for p in parts if p.strip()]

# --- PHASE 1: DECK SYNC & DISCOVERY ---

def scrape_launch_news():
    print(f"📡 Scraping Launch News ({LAUNCH_NEWS_URL})...")
    decks = {}
    try:
        resp = requests.get(LAUNCH_NEWS_URL, headers=HEADERS, timeout=10)
        if resp.status_code != 200: return {}

        soup = BeautifulSoup(resp.content, "html.parser")
        card_pattern = re.compile(r'(ST\d{2}-\d{3})')
        text_content = soup.get_text()
        matches = card_pattern.findall(text_content)
        
        print(f"    ✅ Found {len(matches)} card identifiers.")
        
        if len(matches) < 10: return {}

        for card_id in matches:
            deck_code = card_id.split('-')[0]
            if deck_code not in decks: decks[deck_code] = {}
            decks[deck_code][card_id] = 2 

        return decks
    except: return {}

def hunt_products():
    print(f"\n🕵️ Hunting for Product Metadata...")
    found_decks = {}
    miss_streak = 0
    
    for i in range(1, 21):
        code = f"ST{i:02d}"
        url = PRODUCT_URL_TEMPLATE.format(code.lower())
        try:
            resp = requests.get(url, headers=HEADERS, timeout=2)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, "html.parser")
                title_tag = soup.select_one("h1.ttl, .productName, h1, title")
                raw_title = title_tag.text.strip() if title_tag else f"Starter Deck {code}"
                clean_name = raw_title.split('[')[0].strip().replace("GUNDAM CARD GAME", "").strip()
                
                print(f"    ✅ HIT: {code} -> '{clean_name}'")
                found_decks[code] = {"name": clean_name, "product_url": url}
                miss_streak = 0
            else:
                miss_streak += 1
            
            if miss_streak >= MAX_MISSES: break
            time.sleep(0.1) 
        except:
            miss_streak += 1
            if miss_streak >= MAX_MISSES: break
            
    return found_decks

def sync_decks():
    print("\n--- PHASE 1: SYNCING DECKS ---")
    master_decks = SEED_DECKS.copy()
    news_deck_data = scrape_launch_news()
    if news_deck_data:
        for code, cards in news_deck_data.items():
            master_decks[code] = cards
    else:
        print("    ⚠️ News scrape returned 0 cards. Using verified SEED lists.")

    product_metadata = hunt_products()
    
    if os.path.exists(DECKS_FILE):
        try:
            with open(DECKS_FILE, 'r') as f: 
                existing = json.load(f)
                for k, v in existing.items():
                    if k not in master_decks: master_decks[k] = v
        except: pass
        
    master_metadata = {}
    if os.path.exists(METADATA_FILE):
        try:
            with open(METADATA_FILE, 'r') as f: master_metadata = json.load(f)
        except: pass

    for code, meta in product_metadata.items():
        master_metadata[code] = meta
    
    print(f"    💾 Saving {len(master_decks)} decks...")
    with open(DECKS_FILE, 'w', encoding='utf-8') as f:
        json.dump(master_decks, f, indent=2)
    with open(METADATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(master_metadata, f, indent=2)

    inverted_map = {}
    for deck_id, cards in master_decks.items():
        for card_id, count in cards.items():
            if card_id not in inverted_map: inverted_map[card_id] = {}
            inverted_map[card_id][deck_id] = count
    return inverted_map

# --- PHASE 2: CARD SCRAPING LOGIC ---

def upload_image_to_cloudinary(image_url, public_id):
    global RATE_LIMIT_HIT
    if RATE_LIMIT_HIT: return image_url
    try:
        result = cloudinary.uploader.upload(image_url, public_id=f"gundam_cards/{public_id}", unique_filename=False, overwrite=True)
        return result['secure_url']
    except Exception as e:
        if "420" in str(e) or "Rate Limit" in str(e):
            print(f"    🛑 RATE LIMIT REACHED. Switching to pass-through mode.")
            RATE_LIMIT_HIT = True
        return image_url

def discover_sets():
    print("\n--- PHASE 2: SET DISCOVERY ---")
    found_sets = []
    PROBE_TIMEOUT = 5
    for prefix in KNOWN_SET_PREFIXES:
        print(f"    Checking {prefix} series...", end="")
        set_miss_streak = 0
        for i in range(1, 10):
            set_code = f"{prefix}{i:02d}"
            url = DETAIL_URL_TEMPLATE.format(f"{set_code}-001")
            exists = False
            try:
                resp = requests.get(url, headers=HEADERS, timeout=PROBE_TIMEOUT) 
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.content, "html.parser")
                    if soup.select_one(".cardName") or soup.select_one("h1.name"):
                        exists = True
            except: pass

            if exists:
                found_sets.append({"code": set_code, "limit": 200})
                set_miss_streak = 0
            else:
                set_miss_streak += 1
                if set_miss_streak >= 2: break 
        print(" Done.")
    if not found_sets: return [{"code": "ST01", "limit": 30}]
    return found_sets

def scrape_card_variants(base_card_id, deck_info_map, existing_db=None):
    """
    Scrapes base card + variants.
    Ties RARITY to the site's rarity list.
    Logic: Uses index mapping from rarity list. If image exists but list runs out, appends '+'.
    """
    url = DETAIL_URL_TEMPLATE.format(base_card_id)
    base_stats = None
    rarity_list = []

    # 1. Fetch Base Card Stats
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10) 
        if resp.status_code != 200: return []
        if "cardlist" in resp.url: return []

        soup = BeautifulSoup(resp.content, "html.parser")
        
        name_tag = soup.select_one(".cardName, h1")
        if not name_tag: return []
        name = name_tag.text.strip()
        if not name or name == "Card List" or name == "GUNDAM CARD GAME": 
            return []

        # --- Data Extraction ---
        raw_stats = {"cost": "0", "hp": "0", "ap": "0", "level": "0", "rarity": "-", "color": "N/A", "type": "UNIT", "trait": "-", "zone": "-", "link": "-", "source": "-", "release": "-"}
        for dt in soup.find_all("dt"):
            label = dt.text.strip().lower()
            val = dt.find_next_sibling("dd").text.strip() if dt.find_next_sibling("dd") else ""
            if "cost" in label: raw_stats["cost"] = val
            elif "hp" in label: raw_stats["hp"] = val
            elif "ap" in label or "atk" in label: raw_stats["ap"] = val
            elif "color" in label: raw_stats["color"] = val
            elif "type" in label: raw_stats["type"] = val
            elif "trait" in label: raw_stats["trait"] = val
            elif "release" in label or "where" in label: raw_stats["release"] = val
            elif "rarity" in label: raw_stats["rarity"] = val
            elif "lv" in label or "level" in label: raw_stats["level"] = val
            elif "link" in label: raw_stats["link"] = val

        # --- PARSE RARITIES FROM TEXT ---
        if soup.select_one(".rarity"): 
            raw_rarity_text = soup.select_one(".rarity").text.strip()
            rarity_list = extract_rarities(raw_rarity_text)
            raw_stats["rarity"] = rarity_list[0] 
        else:
            rarity_list = [raw_stats["rarity"]]

        block_icon = safe_int(soup.select_one(".blockIcon").text.strip()) if soup.select_one(".blockIcon") else 0
        effect_text = soup.select_one(".cardDataRow.overview .dataTxt").text.strip().replace("<br>", "\n") if soup.select_one(".cardDataRow.overview .dataTxt") else ""
        
        deck_quantities = deck_info_map.get(base_card_id, {})

        base_stats = {
            "card_no": base_card_id, 
            "name": name, 
            "series": base_card_id.split("-")[0],
            "cost": safe_int(raw_stats["cost"]), 
            "hp": safe_int(raw_stats["hp"]), 
            "ap": safe_int(raw_stats["ap"]),
            "level": safe_int(raw_stats["level"]), 
            "link": raw_stats["link"], 
            "color": raw_stats["color"], 
            "rarity": raw_stats["rarity"], 
            "type": raw_stats["type"],
            "block_icon": block_icon, 
            "trait": raw_stats["trait"], 
            "effect_text": effect_text,
            "release_pack": raw_stats["release"],
            "deck_quantities": deck_quantities, 
            "available_rarities": rarity_list, 
            "last_updated": int(time.time()) 
        }

    except: return []

    if not base_stats: return []

    # 2. Iterate Variants (Base -> p1 -> p2 -> ...)
    found_cards = []
    variant_index = 0

    while True:
        suffix = "" if variant_index == 0 else f"_p{variant_index}"
        current_id = f"{base_card_id}{suffix}"
        target_image_url = IMAGE_URL_TEMPLATE.format(current_id)

        # Stop if image missing
        if not check_url_exists(target_image_url):
            if variant_index == 0: return [] 
            else: break

        card_entry = base_stats.copy()
        card_entry["id"] = current_id 
        
        # --- FIXED RARITY LOGIC ---
        if variant_index < len(rarity_list):
            # If the site listed 3 rarities and we are on image 2, use the list
            card_entry["rarity"] = rarity_list[variant_index]
        else:
            # Fallback: We found an image (_p1) but the text only said "C".
            # This implies a Parallel Art (unlisted). Append a '+' to the last known rarity.
            last_known = rarity_list[-1]
            card_entry["rarity"] = f"{last_known}+"
        # --------------------------

        # Handle Cloudinary
        existing_card = existing_db.get(current_id) if existing_db else None
        final_image_url = ""
        
        if existing_card and "image_url" in existing_card and "cloudinary.com" in existing_card["image_url"]:
             final_image_url = existing_card["image_url"]
        else:
             final_image_url = upload_image_to_cloudinary(target_image_url, current_id)
        
        card_entry["image_url"] = final_image_url
        found_cards.append(card_entry)
        
        variant_index += 1
        if variant_index > 20: break 

    return found_cards

# --- PHASE 3: SANITATION ---

def purge_bad_data(db):
    print("\n--- PHASE 4: QUALITY CONTROL PURGE ---")
    valid_db = {}
    purged_count = 0
    
    for key, card in db.items():
        is_bad = False
        if not card.get('name') or card['name'] == "-": is_bad = True
        if not card.get('image_url'): is_bad = True
        if not card.get('type'): is_bad = True
            
        if is_bad:
            print(f"    🗑️ Purging {key} (Incomplete Data)")
            purged_count += 1
        else:
            valid_db[key] = card

    print(f"    ✨ Cleanup Complete. Removed {purged_count} invalid records. Kept {len(valid_db)}.")
    return valid_db

def save_db(db):
    if len(db) > 0:
        data_list = list(db.values())
        print(f"    💾 Checkpoint: Saving {len(data_list)} total cards...")
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(data_list, f, indent=2, ensure_ascii=False)

def run_update():
    deck_map = sync_decks()
    
    master_db = {}
    if os.path.exists(JSON_FILE):
        print(f"📂 Loading existing {JSON_FILE}...")
        try:
            with open(JSON_FILE, 'r', encoding='utf-8') as f:
                data_list = json.load(f)
                for c in data_list:
                    key = c.get('id', c.get('cardNo'))
                    if key: master_db[key] = c
        except: pass
    
    if not all([os.getenv('CLOUDINARY_CLOUD_NAME'), os.getenv('CLOUDINARY_API_KEY')]):
        print("\n    🛑 WARNING: Cloudinary credentials missing.")

    sets = discover_sets()
    
    print(f"\n--- PHASE 3: CARD AUDIT ({'FULL' if FULL_CHECK else 'INCREMENTAL'}) ---")
    
    for set_info in sets:
        code = set_info['code']
        limit = set_info['limit']
        print(f"\nProcessing Set: {code} (Limit {limit})...")
        miss_streak = 0
        
        for i in range(1, limit + 1):
            base_card_id = f"{code}-{i:03d}"
            
            found_variants = scrape_card_variants(base_card_id, deck_map, existing_db=master_db)
            
            if found_variants:
                for new_card_data in found_variants:
                    c_id = new_card_data['id']
                    existing_card = master_db.get(c_id)
                    
                    if has_changed(existing_card, new_card_data):
                        status = "UPDATE" if existing_card else "NEW"
                        # Print rarity to verify fix
                        print(f"    📝 {status}: {c_id} (Rarity: {new_card_data['rarity']})")        
                        master_db[c_id] = new_card_data
                
                miss_streak = 0
            else:
                miss_streak += 1
                if miss_streak <= MAX_MISSES:
                    print(f"    . {base_card_id} not found (Miss {miss_streak}/{MAX_MISSES})")
                else:
                    print(f"    🛑 Max misses reached for {code}. Moving to next set.")
                    break 
            
            time.sleep(0.1) 
            if i % 50 == 0: save_db(master_db)

    master_db = purge_bad_data(master_db)
    save_db(master_db)

    print("\n✅ Update Complete.")

if __name__ == "__main__":
    run_update()

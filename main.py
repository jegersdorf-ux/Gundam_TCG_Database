import requests
from bs4 import BeautifulSoup
import json
import os
import time
import datetime
import cloudinary
import cloudinary.uploader
import re

# --- CONFIGURATION ---
# Official Site URLs
SEARCH_PAGE_URL = "https://www.gundam-gcg.com/en/cards/"
DETAIL_URL_TEMPLATE = "https://www.gundam-gcg.com/en/cards/detail.php?detailSearch={}"
# High-Res Image Pattern (Verified)
IMAGE_URL_TEMPLATE = "https://www.gundam-gcg.com/en/images/cards/card/{}.webp?251120"

JSON_FILE = "data.json" 

# Cloudinary Setup
cloudinary.config(
  cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME'),
  api_key = os.getenv('CLOUDINARY_API_KEY'),
  api_secret = os.getenv('CLOUDINARY_API_SECRET'),
  secure = True
)

# Headers to mimic a browser
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def upload_image_to_cloudinary(image_url, public_id):
    """
    Uploads an image URL directly to Cloudinary.
    """
    try:
        # Optimization: Cloudinary can fetch remote URLs directly.
        # We don't need to download to a temp file first.
        result = cloudinary.uploader.upload(
            image_url,
            public_id=f"gundam_cards/{public_id}",
            unique_filename=False,
            overwrite=True
        )
        return result['secure_url']
    except Exception as e:
        print(f"   ❌ Cloudinary Error ({public_id}): {e}")
        # Fallback: Return original URL if upload fails so app still has an image
        return image_url

def discover_sets():
    """
    Scrapes the search page to find all current Set Codes (GD01, ST01, etc.)
    """
    print("🔍 Auto-discovering sets from official site...")
    sets = []
    try:
        resp = requests.get(SEARCH_PAGE_URL, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.content, "html.parser")
        
        seen = set()
        # Find options in the Product dropdown
        for option in soup.select("select option"):
            text = option.text.strip()
            # Extract [GD01] pattern
            match = re.search(r"\[([A-Z]{2}\d{2})\]", text)
            if match:
                code = match.group(1)
                if code not in seen:
                    # Estimate count: Starters ~30, Boosters ~130
                    limit = 130 if "GD" in code else 35
                    sets.append({"code": code, "limit": limit})
                    seen.add(code)
                    print(f"   Found Set: {code}")
    except Exception as e:
        print(f"   ⚠️ Discovery failed: {e}. Using defaults.")
        return [{"code": "ST01", "limit": 20}, {"code": "GD01", "limit": 105}]
    
    return sets

def scrape_card(card_id):
    url = DETAIL_URL_TEMPLATE.format(card_id)
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=5)
        # If redirect or 404, card doesn't exist
        if resp.status_code != 200: return None 
            
        soup = BeautifulSoup(resp.content, "html.parser")
        
        # VALIDATION: Check if page has a name title
        name_tag = soup.select_one(".cardName, h1")
        if not name_tag: return None
        name = name_tag.text.strip()

        # STATS PARSING (Level, Cost, HP, AP, Rarity)
        stats = {"level": "-", "cost": "-", "hp": "-", "ap": "-", "rarity": "-", "color": "N/A", "type": "UNIT"}
        
        # Iterate through definition lists <dl><dt>Label</dt><dd>Value</dd></dl>
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

        # TEXT & TRAITS
        text_tag = soup.select_one(".text")
        effect_text = text_tag.text.strip().replace("<br>", "\n") if text_tag else ""
        
        traits_tag = soup.select_one(".characteristic")
        traits = traits_tag.text.strip() if traits_tag else ""

        # IMAGE HANDLING
        # 1. Construct Official High-Res URL
        official_img_url = IMAGE_URL_TEMPLATE.format(card_id)
        
        # 2. Upload to Cloudinary
        final_image_url = upload_image_to_cloudinary(official_img_url, card_id)

        print(f"   ✅ {card_id} | {name}")

        # BUILD FINAL OBJECT
        return {
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
            
            # STORE EXTRA STATS IN METADATA STRING
            # This is what your app parses to find Level and HP
            "metadata": json.dumps({ 
                "level": stats["level"],
                "hp": stats["hp"],
                "def": stats["hp"],
                "atk": stats["ap"],
                "trait": traits,
                "type": stats["type"],
                "variants": [] # Placeholder for now
            }),
            "last_updated": str(datetime.datetime.now())
        }

    except Exception as e:
        print(f"   ❌ Error {card_id}: {e}")
        return None

def run_update():
    sets = discover_sets()
    all_cards = []
    
    print(f"\n--- STARTING SCRAPE ---")
    
    for set_info in sets:
        code = set_info['code']
        limit = set_info['limit']
        print(f"\nProcessing Set: {code}...")
        
        miss_streak = 0
        for i in range(1, limit + 1):
            card_id = f"{code}-{i:03d}"
            
            # Stop searching this set if 5 cards in a row are missing
            if miss_streak >= 5:
                print(f"   Stopping {code} at {i-5} (End of Set)")
                break

            card_data = scrape_card(card_id)
            
            if card_data:
                all_cards.append(card_data)
                miss_streak = 0
            else:
                miss_streak += 1
            
            time.sleep(0.1) # Be polite to server

    # SAVE TO JSON
    if len(all_cards) > 0:
        print(f"\nSaving {len(all_cards)} cards to {JSON_FILE}...")
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_cards, f, indent=2, ensure_ascii=False)
        print("Done.")
    else:
        print("❌ No cards found.")

if __name__ == "__main__":
    run_update()

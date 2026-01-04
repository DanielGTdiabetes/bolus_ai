from pathlib import Path
from PIL import Image, ImageDraw
import io

# Coordinate Mapping (Frontend Logic Ported)
# Percentages 0-100
COORDS = {
    # Abdomen (using Point 2 aka offset 17 as center of zone)
    "abd_r_top": {"file": "body_abdomen.png", "x": 67, "y": 42},
    "abd_r_mid": {"file": "body_abdomen.png", "x": 67, "y": 58},
    "abd_r_bot": {"file": "body_abdomen.png", "x": 67, "y": 74},
    "abd_l_top": {"file": "body_abdomen.png", "x": 33, "y": 42},
    "abd_l_mid": {"file": "body_abdomen.png", "x": 33, "y": 58},
    "abd_l_bot": {"file": "body_abdomen.png", "x": 33, "y": 74},
    
    # Legs/Glutes
    "glute_left":  {"file": "body_legs.png", "x": 32, "y": 38},
    "glute_right": {"file": "body_legs.png", "x": 68, "y": 38},
    "leg_left":    {"file": "body_legs.png", "x": 15, "y": 60},
    "leg_right":   {"file": "body_legs.png", "x": 85, "y": 60},
}

def generate_injection_image(site_id: str, assets_dir: Path) -> io.BytesIO:
    """
    Loads generic body image and overlays a target on the specific site.
    Returns bytes ready for Telegram.
    """
    # Parse ID: "abd_r_top:1" -> zone="abd_r_top", point=1
    if ":" in site_id:
        zone_id, point_str = site_id.split(":")
        try:
            point = int(point_str)
        except:
            point = 1
    else:
        zone_id = site_id
        point = 1

    # Determine Base Image and Coords
    img_file = "body_full.png" # Safe fallback
    cx_pct, cy_pct = 50, 50 # Default center
    found = False

    # Abdomen Logic (Dynamic mapping to match Frontend)
    if "abd_" in zone_id:
        img_file = "body_abdomen.png"
        found = True
        
        # Y Calc (Rows)
        if "_top" in zone_id: cy_pct = 42
        elif "_mid" in zone_id: cy_pct = 58
        elif "_bot" in zone_id: cy_pct = 74
        else: cy_pct = 58 # Fallback

        # X Calc (Columns/Offsets)
        # Offsets for P1, P2, P3: [8, 17, 26]
        offsets = [8, 17, 26] 
        # Cap point between 1 and 3 just in case
        idx = max(0, min(point - 1, 2))
        dist = offsets[idx]
        
        if "_l_" in zone_id:
            cx_pct = 50 - dist
        else: # "_r_"
            cx_pct = 50 + dist
            
    # Basal/Legs Logic (Static Map or Simple)
    elif zone_id in COORDS:
        info = COORDS[zone_id]
        img_file = info["file"]
        cx_pct = info["x"]
        cy_pct = info["y"]
        found = True

    if not found:
        return None

    img_path = assets_dir / img_file
    if not img_path.exists():
        return None

    try:
        with Image.open(img_path) as im:
            im = im.convert("RGBA")
            draw = ImageDraw.Draw(im)
            
            w, h = im.size
            cx = (cx_pct / 100.0) * w
            cy = (cy_pct / 100.0) * h
            
            # Style: Green target circle (Matching Frontend style roughly)
            r = 15 # radius
            # Outer fading ring (simulated)
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(37, 99, 235, 100), outline=(30, 64, 175), width=2)
            
            # Inner dot
            r_inner = 5
            draw.ellipse((cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner), fill=(255, 255, 255, 255))
            
            # Output
            bio = io.BytesIO()
            im.save(bio, format="PNG")
            bio.seek(0)
            bio.name = "injection_site.png"
            return bio
    except Exception as e:
        print(f"Image generation failed: {e}")
        return None

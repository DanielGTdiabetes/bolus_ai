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
    # Handle IDs with point suffix (e.g. abd_l_top:1)
    base_id = site_id.split(":")[0] if ":" in site_id else site_id
    info = COORDS.get(base_id)
    if not info:
        return None

    img_path = assets_dir / info["file"]
    if not img_path.exists():
        return None

    try:
        with Image.open(img_path) as im:
            im = im.convert("RGBA")
            draw = ImageDraw.Draw(im)
            
            w, h = im.size
            cx = (info["x"] / 100.0) * w
            cy = (info["y"] / 100.0) * h
            
            # Style: Green target circle
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
            return bio
    except Exception as e:
        print(f"Image generation failed: {e}")
        return None

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

def generate_injection_image(site_id: str, assets_dir: Path, mode: str = "selected", secondary_site_id: str = None) -> io.BytesIO:
    """
    Loads generic body image and overlays targets.
    Primary 'site_id' is the main focus (Next).
    Secondary 'secondary_site_id' is optional (Last).
    
    Modes:
    - 'next_last_combined': site_id=Next(Green), secondary=Last(Red)
    - 'selected': site_id=Blue (Single)
    - 'recommended': site_id=Green (Single)
    - 'last': site_id=Red (Single)
    """
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[ImageRenderer] Generating image for site='{site_id}', sec='{secondary_site_id}', mode='{mode}'")

    # Helper to resolve coords
    def resolve_coords(s_id: str):
        if not s_id: return None
        
        # Parse ID: zone:point OR zone (basal default point 1)
        if ":" in s_id:
            z_id, p_str = s_id.split(":")
            try:
                pt = int(p_str)
            except:
                pt = 1
        else:
            z_id = s_id
            pt = 1
            
        # 1. Check Abdomen Logic
        if "abd_" in z_id:
            img = "body_abdomen.png"
            
            # Y Calc
            if "_top" in z_id: cy_pct = 42
            elif "_mid" in z_id: cy_pct = 58
            elif "_bot" in z_id: cy_pct = 74
            else: cy_pct = 58
            
            # X Calc
            offsets = [8, 17, 26]
            idx = max(0, min(pt - 1, 2))
            dist = offsets[idx]
            
            if "_l_" in z_id:
                cx_pct = 50 + dist
            else:
                cx_pct = 50 - dist
                
            return {"file": img, "x": cx_pct, "y": cy_pct, "point": pt, "align_right": ("_l_" in z_id)}

        # 2. Check Static Map
        if z_id in COORDS:
            base = COORDS[z_id]
            # Basal usually doesn't have points, but we respect input pt if passed
            return {"file": base["file"], "x": base["x"], "y": base["y"], "point": pt, "align_right": (base.get("x") > 50)}
        
        return None

    # Resolve Primary
    primary = resolve_coords(site_id)
    if not primary:
        logger.warning(f"Primary site {site_id} not found coords")
        return None

    # Resolve Secondary
    secondary = resolve_coords(secondary_site_id)
    
    # Check Compatibility
    img_file = primary["file"]
    if secondary and secondary["file"] != img_file:
        logger.warning("Primary and Secondary on different body parts. Skipping secondary.")
        secondary = None
    
    img_path = assets_dir / img_file
    if not img_path.exists():
        logger.warning(f"Image not found: {img_path}")
        return None

    try:
        with Image.open(img_path) as im:
            im = im.convert("RGBA")
            w, h = im.size
            
            # Crop to square if needed
            if w != h:
                new_size = min(w, h)
                left = (w - new_size) / 2
                top = (h - new_size) / 2
                right = (w + new_size) / 2
                bottom = (h + new_size) / 2
                im = im.crop((left, top, right, bottom))
                w, h = im.size
                
            draw = ImageDraw.Draw(im)
            msg_scale = w / 300.0
            
            # Helper Draw Function
            def draw_point(coords, color_fill, color_stroke, label=None):
                if not coords: return
                cx = (coords["x"] / 100.0) * w
                cy = (coords["y"] / 100.0) * h
                
                # Rings
                r = 15 * msg_scale
                w_line = max(1, int(2 * msg_scale))
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color_fill, outline=color_stroke, width=w_line)
                
                # Center Dot
                r_inner = 5 * msg_scale
                draw.ellipse((cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner), fill=(255, 255, 255, 255))
                
                # Number
                if coords["point"] is not None:
                     text_val = str(coords["point"])
                     # Centering rough approx
                     draw.text((cx-3, cy-5), text_val, fill=(0,0,0,255))

            # Define Colors
            c_blue_fill = (37, 99, 235, 120)
            c_blue_str = (30, 64, 175)
            c_green_fill = (74, 222, 128, 140)
            c_green_str = (22, 163, 74)
            c_red_fill = (248, 113, 113, 140)
            c_red_str = (220, 38, 38)

            # Draw Secondary (Last) first (Red)
            if secondary:
                draw_point(secondary, c_red_fill, c_red_str)
                
            # Draw Primary (Next)
            if mode == "next_last_combined":
                 draw_point(primary, c_green_fill, c_green_str)
            elif mode == "recommended":
                 draw_point(primary, c_green_fill, c_green_str)
            elif mode == "last":
                 draw_point(primary, c_red_fill, c_red_str)
            else: # selected
                 draw_point(primary, c_blue_fill, c_blue_str)

            # Draw L/R Labels
            try:
                draw.text((w*0.05, h*0.05), "DER", fill=(100,100,100,128))
                draw.text((w*0.90, h*0.05), "IZQ", fill=(100,100,100,128))
            except: pass
            
            # Save
            bio = io.BytesIO()
            im.save(bio, format="PNG")
            bio.seek(0)
            
            import uuid
            nonce = uuid.uuid4().hex[:6]
            bio.name = f"injection_{site_id}_{nonce}.png"
            return bio

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Image generation failed: {e}")
        return None

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

def generate_injection_image(site_id: str = None, assets_dir: Path = None, mode: str = "selected", secondary_site_id: str = None, next_site_id: str = None, last_site_id: str = None) -> io.BytesIO:
    """
    Generates body image with overlays.
    
    Arguments:
    - next_site_id: The Next Point (green).
    - last_site_id: The Last/Previous Point (red).
    - site_id: Legacy/Generic primary ID (blue if mode='selected').
    
    If next_site_id/last_site_id are provided, they take precedence over 'site_id' for the combined view.
    """
    import logging
    logger = logging.getLogger(__name__)

    # Logic:
    # 1. If we have next_site_id OR last_site_id, we use Combined Mode behavior.
    # 2. Else we fall back to site_id and mode (selected/recommended/last).
    
    # Resolve explicit args
    p_next = next_site_id
    p_last = last_site_id
    
    # Fallback to legacy args if explicit ones missing
    if not p_next and not p_last and site_id:
        if mode == "next_last_combined":
             p_next = site_id
             p_last = secondary_site_id
             # IMPLICIT ASSUMPTION: site_id is Next(Green), secondary is Last(Red)
             # This was the source of confusion. We will remove this implicit logic by prioritizing explicitly named args.
        elif mode == "recommended":
             p_next = site_id
        elif mode == "last":
             p_last = site_id
        else:
             # Default generic (Blue)
             pass

    logger.info(f"[ImageRenderer] Gen Next='{p_next}' Last='{p_last}' (Legacy: site='{site_id}' mode='{mode}')")

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

    coords_next = resolve_coords(p_next)
    coords_last = resolve_coords(p_last)
    coords_generic = resolve_coords(site_id) if not p_next and not p_last else None
    
    # Determine base image
    # Prioritize Next, then Last, then Generic
    main_ref = coords_next or coords_last or coords_generic
    if not main_ref:
        logger.warning(f"No valid coords found for any site. {p_next}|{p_last}|{site_id}")
        return None
        
    img_file = main_ref["file"]
    
    # Verify compatibility (skip if different body part)
    if coords_next and coords_next["file"] != img_file: coords_next = None
    if coords_last and coords_last["file"] != img_file: coords_last = None
    
    img_path = assets_dir / img_file
    if not img_path.exists():
        logger.warning(f"Image not found: {img_path}")
        return None

    try:
        with Image.open(img_path) as im:
            im = im.convert("RGBA")
            w, h = im.size
            
            # Crop to square
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
                     draw.text((cx-3, cy-5), text_val, fill=(0,0,0,255))

            # Define Colors
            c_blue_fill = (37, 99, 235, 120)
            c_blue_str = (30, 64, 175)
            c_green_fill = (74, 222, 128, 140)
            c_green_str = (22, 163, 74)
            c_red_fill = (248, 113, 113, 140)
            c_red_str = (220, 38, 38)
            
            # Draw Process:
            if p_next or p_last:
                # Combined Mode
                if coords_last:
                    draw_point(coords_last, c_red_fill, c_red_str) # Last = Red
                if coords_next:
                    draw_point(coords_next, c_green_fill, c_green_str) # Next = Green
            else:
                # Generic Mode (Blue)
                draw_point(coords_generic, c_blue_fill, c_blue_str)

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
            # Use safe ID for filename
            clean_id = (p_next or p_last or site_id or "unknown").replace(":", "_")
            bio.name = f"injection_{clean_id}_{nonce}.png"
            return bio

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Image generation failed: {e}")
        return None

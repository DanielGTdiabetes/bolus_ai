from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

class FilterConfig(BaseModel):
    enabled: bool = True
    night_start_hour: int = 23
    night_end_hour: int = 7
    drop_threshold_mgdl: float = 15.0
    drop_window_minutes: int = 5
    rebound_threshold_mgdl: float = 15.0
    rebound_window_minutes: int = 15
    max_low_duration_minutes: int = 25
    treatments_lookback_minutes: int = 120
    # IOB threshold could be checked if we have that data stream, for now we will rely on treatments

class CompressionDetector:
    def __init__(self, config: FilterConfig):
        self.config = config

    def detect(
        self, 
        entries: List[Any], 
        treatments: List[Any] = []
    ) -> List[Any]:
        """
        Analyzes a list of Nightscout SGV entries and flags suspected compression lows.
        Entries are expected to be Pydantic models or dicts with 'sgv', 'date' (ms), 'direction'.
        Returns a NEW list of entries with added flags:
          - is_compression: bool
          - compression_reason: str
        """
        if not self.config.enabled:
            return entries

        # Convert to working list of dicts if models
        work_entries = []
        for e in entries:
            d = e.model_dump() if hasattr(e, 'model_dump') else e.dict() if hasattr(e, 'dict') else e.copy()
            work_entries.append(d)
        
        # Sort by date ASCENDING for processing
        work_entries.sort(key=lambda x: x['date'])
        
        n = len(work_entries)
        if n < 3:
            return work_entries

        # We need efficient lookups for treatments.
        # Treatments usually have 'created_at' (str) or 'date' (ms, sometimes)
        # We'll create a sorted list of treatment timestamps
        treat_times = []
        for t in treatments:
            # Handle model vs dict
            td = t.model_dump() if hasattr(t, 'model_dump') else t.dict() if hasattr(t, 'dict') else t
            ts = self._get_timestamp(td)
            if ts:
                treat_times.append(ts)
        treat_times.sort()
        
        for i in range(1, n - 1):
            curr = work_entries[i]
            val = float(curr['sgv'])
            
            # 1. Check if potential Low
            if val >= 70:
                continue
                
            # 2. Check Time Window (Night)
            dt = datetime.fromtimestamp(curr['date'] / 1000.0)
            h = dt.hour
            is_night = False
            if self.config.night_start_hour > self.config.night_end_hour:
                # e.g. 23 to 7: >= 23 OR < 7
                if h >= self.config.night_start_hour or h < self.config.night_end_hour:
                    is_night = True
            else:
                # e.g. 0 to 6
                if self.config.night_start_hour <= h < self.config.night_end_hour:
                    is_night = True
            
            if not is_night:
                continue

            # 3. Check for recent treatments (Carbs or Bolus)
            # If there was a treatment in the last X minutes, it might be a real Reactive Hypo or IOB drop
            # We skip flagging if treatment recently
            if self._has_recent_treatment(curr['date'], treat_times):
                continue

            # 4. Pattern Recognition
            # We look backward for Drop and forward for Rebound
            
            # DROP Analysis
            # Look at previous points (within drop_window_minutes)
            # Find the max value in that window that is noticeably higher
            prev_idx = i - 1
            max_pre = val
            valid_drop = False
            
            while prev_idx >= 0:
                p = work_entries[prev_idx]
                t_diff = (curr['date'] - p['date']) / 60000.0
                if t_diff > self.config.drop_window_minutes + 2: # Tolerance
                    break
                
                p_val = float(p['sgv'])
                if p_val - val >= self.config.drop_threshold_mgdl:
                    valid_drop = True
                    max_pre = p_val
                    break # Found the drop source
                prev_idx -= 1
            
            if not valid_drop:
                continue

            # REBOUND Analysis
            # Look ahead for rapid recovery
            next_idx = i + 1
            valid_rebound = False
            
            while next_idx < n:
                nxt = work_entries[next_idx]
                t_diff = (nxt['date'] - curr['date']) / 60000.0
                
                # If duration of low exceeds max allowed, abort
                # (This logic is a bit slightly distinct: we are looking for the rebound point.
                # If we don't find it within rebound_window, we assume it's a long low = real.)
                if t_diff > self.config.rebound_window_minutes + 2:
                    break
                    
                n_val = float(nxt['sgv'])
                if n_val - val >= self.config.rebound_threshold_mgdl:
                    valid_rebound = True
                    break
                next_idx += 1
                
            if valid_rebound:
                # Mark this point
                curr['is_compression'] = True
                curr['compression_reason'] = (
                    f"Night drop (-{int(max_pre - val)}) & rebound "
                    f"in time limits. No recent treats."
                )
                
                # Optional: Mark adjacent points in the trough?
                # The user asked to mark segments.
                # A simple approach is: iterate, if we find a 'center' point, mark it.
                # But a compression might differ by 1-2 frames. i, i+1 might both be low.
                # Let's keep it simple: strict point checking for now as requested by user prompt "Marcar como posible compresión".
                # If multiple points satisfy, they get marked.

        return work_entries

    def _get_timestamp(self, item: Dict) -> Optional[float]:
        # Helper to get ms timestamp
        if 'date' in item and isinstance(item['date'], (int, float)):
            return float(item['date'])
        if 'created_at' in item: # ISO string
            try:
                dt = datetime.fromisoformat(item['created_at'].replace("Z", "+00:00"))
                return dt.timestamp() * 1000.0
            except:
                pass
        return None

    def _has_recent_treatment(self, current_ms: float, treat_times: List[float]) -> bool:
        # Check if any treatment exists in [now - lookback, now]
        # We can optimize since treat_times is sorted, bu linear scan is fine for small lists (~20 items)
        limit_ms = self.config.treatments_lookback_minutes * 60000
        cutoff = current_ms - limit_ms
        
        for t in treat_times:
            if cutoff <= t <= current_ms: # Treatment happened before (or exactly same time)
                return True
        return False

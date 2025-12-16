import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.learning import MealEntry, MealOutcome
from app.services.nightscout_client import NightscoutClient, NightscoutSGV

logger = logging.getLogger(__name__)

class LearningService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_meal_entry(
        self,
        user_id: str,
        items: List[str],
        carbs: float,
        fat: float,
        protein: float,
        bolus_data: dict, # {kind, total, upfront, later, delay}
        context: dict = None # {bg, trend, etc}
    ) -> MealEntry:
        """
        Records a new meal entry for future learning.
        """
        entry = MealEntry(
            user_id=user_id,
            items=items,
            carbs_g=carbs,
            fat_g=fat,
            protein_g=protein,
            
            bolus_kind=bolus_data.get("kind"),
            bolus_u_total=bolus_data.get("total"),
            bolus_u_upfront=bolus_data.get("upfront"),
            bolus_u_later=bolus_data.get("later"),
            bolus_delay_min=bolus_data.get("delay"),
            
            start_bg=context.get("bg") if context else None,
            start_trend=context.get("trend") if context else None,
            start_iob=context.get("iob") if context else None
        )
        self.session.add(entry)
        await self.session.commit()
        await self.session.refresh(entry)
        logger.info(f"Memory: Saved MealEntry {entry.id} ({items})")
        return entry

    async def find_similar_meals(self, query_items: List[str], limit: int = 3) -> List[MealEntry]:
        """
        Finds past meals containing similar items.
        Currently uses simple set intersection or substring match.
        """
        if not query_items:
            return []
            
        # This is a naive implementation; vector search would be better later.
        # We fetch recent entries and filter dynamically for now (assuming low volume).
        # Optimization: Use Postgres Array intersection if we change schema to Arrays vs JSONB.
        
        # Fetch last 100 entries with outcomes
        stmt = select(MealEntry).where(MealEntry.outcome != None).order_by(MealEntry.created_at.desc()).limit(100)
        result = await self.session.execute(stmt)
        candidates = result.scalars().all()
        
        matches = []
        query_set = set(q.lower() for q in query_items)
        
        for entry in candidates:
            # Check overlap
            if not entry.items: 
                continue
                
            entry_items = [str(x).lower() for x in entry.items]
            # Simple scoring: count of shared words/tokens
            score = 0
            for q in query_set:
                for target in entry_items:
                    if q in target or target in q:
                        score += 1
            
            if score > 0:
                matches.append((score, entry))
                
        matches.sort(key=lambda x: x[0], reverse=True)
        return [m[1] for m in matches[:limit]]

    async def evaluate_pending_outcomes(self, ns_client: NightscoutClient):
        """
        Checks entries older than 4h that have no outcome.
        Computes score based on NS data.
        """
        # Find entries > 4h ago and < 24h ago with no outcome
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=4)
        old_limit = now - timedelta(hours=24)
        
        stmt = select(MealEntry).outerjoin(MealOutcome).where(
            MealOutcome.id == None,
            MealEntry.created_at < cutoff,
            MealEntry.created_at > old_limit
        )
        
        result = await self.session.execute(stmt)
        pending = result.scalars().all()
        
        if not pending:
            return
            
        logger.info(f"Memory: Evaluating {len(pending)} pending meal outcomes...")
        
        for entry in pending:
            try:
                await self._compute_outcome(entry, ns_client)
            except Exception as e:
                logger.error(f"Failed to evaluate entry {entry.id}: {e}")

    async def _compute_outcome(self, entry: MealEntry, ns_client: NightscoutClient):
        # 1. Fetch SGV data for [entry.created_at, entry.created_at + 4h]
        start_dt = entry.created_at.replace(tzinfo=timezone.utc)
        end_dt = start_dt + timedelta(hours=4)
        
        # Convert to ISO strings for NS API if needed, or implement range fetch in client
        # Adding a helper in NS client or fetching 'count' and filtering is inefficient.
        # Ideally NS Client supports date range. 
        # Assuming we can fetch treatments/entries around date.
        
        # For MVP: We fetch last 6h (count=72) and filter locally if easy, 
        # OR we rely on a new client method `get_sgvs_window`.
        
        # Let's assume we implement get_sgvs_window(start, end)
        sgvs = await ns_client.get_sgvs_window(start_dt, end_dt)
        if not sgvs or len(sgvs) < 12: # Need at least ~1h of data to judge
            logger.warning(f"Insufficient data for {entry.id}")
            return

        values = [s.sgv for s in sgvs]
        max_bg = max(values)
        min_bg = min(values)
        final_bg = values[0] # closest to end_dt (descending usually, but we sort)
        
        # Check specific order
        sgvs.sort(key=lambda x: x.date) # asc
        final_bg = sgvs[-1].sgv
        
        # Scoring Logic (1-10)
        # 10: No hypo, max < 160, return to range
        # ... logic ...
        score = 10
        
        # Penalties
        if min_bg < 70:
            score -= 5 # severe penalty for hypo
        elif min_bg < 80:
            score -= 2
            
        if max_bg > 250:
            score -= 4
        elif max_bg > 180:
            score -= 2
            
        target = 110 # default assumption
        if final_bg > 160:
            score -= 1 # didn't stick the landing
            
        score = max(1, min(10, score))
        
        outcome = MealOutcome(
            meal_entry_id=entry.id,
            score=score,
            max_bg=max_bg,
            min_bg=min_bg,
            final_bg=final_bg,
            hypo_occurred=(min_bg < 70),
            hyper_occurred=(max_bg > 180),
            evaluated_at=datetime.now(timezone.utc)
        )
        
        self.session.add(outcome)
        await self.session.commit()
        logger.info(f"Memory: Scored Entry {entry.id} -> Score {score}/10")

    async def compute_learning_hint(
        self,
        tags: List[str],
        fat_g: float,
        protein_g: float,
        current_strategy: str = "normal"
    ) -> Optional[dict]:
        """
        Input: tags + macros
        Output: Suggestion to extend bolus or not based on past experiences.
        """
        # 1. Find similar past meals
        # Filter slightly: if user has high fat now, look for high fat past?
        # For now, simplistic tag matching.
        matches = await self.find_similar_meals(tags, limit=10)
        
        if not matches or len(matches) < 3:
            return None
            
        # 2. Analyze outcomes
        # "Short" = High BG (Insulin was short/insufficient or too fast absorption vs meal)
        # "Over" = Low BG (Insulin was too much or too slow absorption)
        
        count = 0
        short_count = 0 # Hyper
        over_count = 0  # Hypo
        
        for m in matches:
            if not m.outcome: continue
            count += 1
            
            # Outcome logic
            # hyper_occurred usually means we didn't cover the spike (Short)
            if m.outcome.hyper_occurred or m.outcome.max_bg > 180:
                short_count += 1
            
            # hypo_occurred means we gave too much or timing wrong (Over)
            if m.outcome.hypo_occurred or m.outcome.min_bg < 70:
                over_count += 1
                
        if count < 3:
            return None
            
        short_rate = short_count / count
        over_rate = over_count / count
        
        # 3. Decision Logic
        suggest_extended = False
        reason = ""
        
        # If we have consistent hypers (short) and it is high fat/protein or "pizza/pasta" context
        high_macros = (fat_g > 15 or protein_g > 20)
        
        if short_rate >= 0.6:
            # Consistent spikes
            if high_macros:
                suggest_extended = True
                reason = f"En {count} comidas similares recientes, tuviste picos altos ({int(short_rate*100)}%). Al ser grasa/proteína, un bolo extendido puede ayudar."
            else:
                reason = f"Tendencia a picos altos en comidas similares ({int(short_rate*100)}%). Revisa ratios."
        
        elif over_rate >= 0.5:
            # Consistent hypos
            reason = f"Cuidado: Tendencia a bajadas en comidas similares ({int(over_rate*100)}%)."
            if current_strategy == "extended":
                # If we were planning extended but history says hypos, maybe warn against over-bolusing?
                # Complex to say "don't extend", usually extending is safer for hypos than upfront.
                # So we just warn.
                pass

        if suggest_extended:
            return {
                "suggest_extended": True,
                "reason": reason,
                "evidence": {
                    "n": count,
                    "short_rate": round(short_rate, 2),
                    "over_rate": round(over_rate, 2)
                }
            }
        elif reason:
            # Info only
             return {
                "suggest_extended": False,
                "reason": reason,
                "evidence": {
                    "n": count,
                    "short_rate": round(short_rate, 2),
                    "over_rate": round(over_rate, 2)
                }
            }
            
        return None


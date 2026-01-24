export function shouldDegradeSimulation(iobStatus, cobStatus) {
  const bad = ["unavailable", "stale"];
  return bad.includes(iobStatus || "") || bad.includes(cobStatus || "");
}

export function buildHistoryFromSnapshot(iobData, treatments = [], now = new Date()) {
  const events = { boluses: [], carbs: [] };
  const reference = now instanceof Date ? now : new Date(now);
  const seenBoluses = new Set();

  const useBreakdown = iobData && Array.isArray(iobData.breakdown) && iobData.breakdown.length > 0;

  if (useBreakdown) {
    iobData.breakdown.forEach((b) => {
      if (!b.ts || !b.units) return;
      const ts = new Date(b.ts);
      const offset = -1 * Math.round((reference.getTime() - ts.getTime()) / 60000);

      const key = `${offset.toFixed(1)}:${parseFloat(b.units).toFixed(2)}`;

      if (!seenBoluses.has(key)) {
        events.boluses.push({
          time_offset_min: offset,
          units: b.units,
          duration_minutes: b.duration || 0,
        });
        seenBoluses.add(key);
      }
    });
  }

  treatments.forEach((t) => {
    if (!t || !t.created_at) return;
    const ts = new Date(t.created_at);
    const offset = -1 * Math.round((reference.getTime() - ts.getTime()) / 60000);
    const carbs = parseFloat(t.carbs || 0);
    const insulin = parseFloat(t.insulin || 0);

    if (carbs > 0 || t.fiber > 0) {
      events.carbs.push({
        time_offset_min: offset,
        grams: carbs,
        fat_g: parseFloat(t.fat || 0),
        protein_g: parseFloat(t.protein || 0),
        fiber_g: parseFloat(t.fiber || 0),
      });
    }

    // Basal - explicitly ignore for bolus array
    if (t.eventType === 'Basal') {
      // Future: map to events.basal_injections if supported
      return;
    }

    if (!useBreakdown && insulin > 0) {
      const key = `${offset.toFixed(1)}:${insulin.toFixed(2)}`;
      if (!seenBoluses.has(key)) {
        events.boluses.push({
          time_offset_min: offset,
          units: insulin,
          duration_minutes: t.duration || 0,
        });
        seenBoluses.add(key);
      }
    }
  });

  return events;
}

export function buildForecastPayload({
  bgVal,
  targetMgdl,
  isf,
  icr,
  dia,
  peak,
  insulinModel,
  carbAbsorption,
  basalDailyUnits,
  insulinOnset,
  settings, // Add settings to calc multiplier
  slot,
  events
}) {
  // Calculate Resistance Multiplier
  // Logic: Ratio of Current Slot ICR / Lunch ICR (Reference)
  let sensitivityMultiplier = 1.0;
  if (settings && settings.cr && slot) {
    try {
      const icrRef = parseFloat(settings.cr.lunch || 10.0);
      const icrSlot = parseFloat(settings.cr[slot] || icrRef);

      if (icrRef > 0 && icrSlot > 0) {
        const ratio = icrSlot / icrRef;
        // Clamp: Min 0.35 (High Resistance), Max 1.0 (Normal)
        sensitivityMultiplier = Math.min(1.0, Math.max(0.35, ratio));
      }
    } catch (e) {
      console.warn("Error calculating sensitivity multiplier", e);
    }
  }

  return {
    start_bg: bgVal,
    units: 'mgdl',
    horizon_minutes: 240,
    params: {
      isf: isf,
      icr: icr,
      dia_minutes: dia * 60,
      insulin_peak_minutes: peak,
      carb_absorption_minutes: carbAbsorption,
      insulin_model: insulinModel,
      insulin_onset_minutes: insulinOnset,
      insulin_sensitivity_multiplier: sensitivityMultiplier,
      target_bg: targetMgdl,
      basal_daily_units: basalDailyUnits
    },
    events: events
  };
}

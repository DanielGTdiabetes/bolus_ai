export function shouldDegradeSimulation(iobStatus, cobStatus) {
  const bad = ["unavailable", "stale"];
  return bad.includes(iobStatus || "") || bad.includes(cobStatus || "");
}

export function buildHistoryFromSnapshot(iobData, treatments = [], now = new Date()) {
  const events = { boluses: [], carbs: [] };
  const reference = now instanceof Date ? now : new Date(now);

  if (iobData && Array.isArray(iobData.breakdown)) {
    iobData.breakdown.forEach((b) => {
      if (!b.ts || !b.units) return;
      const ts = new Date(b.ts);
      const offset = -1 * Math.round((reference.getTime() - ts.getTime()) / 60000);
      events.boluses.push({
        time_offset_min: offset,
        units: b.units,
        duration_minutes: b.duration || 0,
      });
    });
  }

  treatments.forEach((t) => {
    if (!t || !t.created_at) return;
    const ts = new Date(t.created_at);
    const offset = -1 * Math.round((reference.getTime() - ts.getTime()) / 60000);
    const carbs = parseFloat(t.carbs || 0);
    const insulin = parseFloat(t.insulin || 0);

    if (insulin > 0) {
      events.boluses.push({
        time_offset_min: offset,
        units: insulin,
        duration_minutes: t.duration || 0,
      });
    }

    if (carbs > 0 || t.fiber > 0) {
      events.carbs.push({
        time_offset_min: offset,
        grams: carbs,
        fat_g: parseFloat(t.fat || 0),
        protein_g: parseFloat(t.protein || 0),
        fiber_g: parseFloat(t.fiber || 0),
      });
    }
  });

  return events;
}

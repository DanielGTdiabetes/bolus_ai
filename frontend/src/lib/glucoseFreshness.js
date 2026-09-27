// Age must keep advancing even when the server cannot be reached.
export function glucoseFreshness(data, receivedAt, now, refreshFailed = false) {
    if (!data) return { ageMinutes: null, stale: true };
    const elapsed = Math.max(0, now - receivedAt) / 60000;
    const serverAge = Number.isFinite(data.age_minutes) ? data.age_minutes + elapsed : null;
    const measuredAge = Number.isFinite(data.date) ? (now - data.date) / 60000 : null;
    const ages = [serverAge, measuredAge].filter(Number.isFinite);
    const ageMinutes = ages.length ? Math.max(0, ...ages) : null;
    return {
        ageMinutes,
        stale: refreshFailed || ageMinutes === null || ageMinutes > 10 ||
            (measuredAge !== null && measuredAge < -2) ||
            data.status !== 'ok' || data.is_stale || data.stale || !data.usable_for_dosing,
    };
}

export function subscribeGlucoseResume(refresh, windowObj = window, documentObj = document) {
    const onResume = () => {
        if (documentObj.visibilityState !== 'hidden') refresh();
    };
    const events = ['online', 'focus', 'pageshow', 'bolusai:resume'];
    events.forEach(event => windowObj.addEventListener(event, onResume));
    documentObj.addEventListener('visibilitychange', onResume);
    return () => {
        events.forEach(event => windowObj.removeEventListener(event, onResume));
        documentObj.removeEventListener('visibilitychange', onResume);
    };
}

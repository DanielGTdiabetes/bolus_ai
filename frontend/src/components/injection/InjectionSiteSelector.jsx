import React, { useState, useEffect } from 'react';

/**
 * ZONES DEFINITION CUSTOMIZED
 */
const ZONES = {
    rapid: [
        { id: 'abd_l_top', label: 'Abd. Izq - Arriba', count: 3 },
        { id: 'abd_l_mid', label: 'Abd. Izq - Medio', count: 3 },
        { id: 'abd_l_bot', label: 'Abd. Izq - Bajo', count: 3 },
        { id: 'abd_r_top', label: 'Abd. Der - Arriba', count: 3 },
        { id: 'abd_r_mid', label: 'Abd. Der - Medio', count: 3 },
        { id: 'abd_r_bot', label: 'Abd. Der - Bajo', count: 3 },
    ],
    basal: [
        { id: 'leg_left', label: 'Muslo Izq', count: 1 },
        { id: 'leg_right', label: 'Muslo Der', count: 1 },
        { id: 'glute_left', label: 'Glúteo Izq', count: 1 },
        { id: 'glute_right', label: 'Glúteo Der', count: 1 }
    ]
};

// --- Helpers de sesión/API coherentes con el resto del proyecto ---
const TOKEN_KEYS = ['bolusai_token', 'token']; // compat legacy
function getToken() {
    for (const k of TOKEN_KEYS) {
        const v = localStorage.getItem(k);
        if (v) return v;
    }
    return null;
}

function getApiBase() {
    // tu lib/api.ts usa VITE_API_BASE_URL. Aquí lo respetamos.
    const base = (import.meta.env.VITE_API_BASE_URL || window.location.origin);
    return String(base).replace(/\/$/, '');
}

function assetUrl(filename) {
    // Vite: BASE_URL funciona en root o subcarpeta
    const base = import.meta.env.BASE_URL || '/';
    return `${base}${filename}`;
}

export function InjectionSiteSelector({ type, onSelect, selected, autoSelect = false, forcedLastUsed = null }) {
    const [lastUsed, setLastUsed] = useState(null);
    const [recommended, setRecommended] = useState(null);

    const fetchState = async () => {
        try {
            const token = getToken();
            if (!token) throw new Error("No auth token");

            const res = await fetch(`${getApiBase()}/api/injection/state?t=${Date.now()}`, {
                headers: { "Authorization": `Bearer ${token}` }
            });

            if (res.ok) {
                const data = await res.json();
                if (type === 'rapid') return { last: data.bolus, next: data.next_bolus };
                return { last: data.basal, next: data.next_basal };
            }
            throw new Error(`state status ${res.status}`);
        } catch (e) {
            console.warn("API Sync failed, falling back to local", e);
        }

        const history = JSON.parse(localStorage.getItem('injection_history_v2') || '{}');
        return { last: history[type], next: null };
    };

    useEffect(() => {
        const load = async () => {
            const stateObj = await fetchState();
            const lastStr = stateObj?.last;
            const nextStr = stateObj?.next;

            if (lastStr) {
                setLastUsed(lastStr);

                if (nextStr) {
                    setRecommended(nextStr);
                } else {
                    const [lZone, lPointStr] = lastStr.split(':');
                    const lPoint = parseInt(lPointStr);

                    const zoneDef = ZONES[type].find(z => z.id === lZone);

                    if (zoneDef && lPoint < zoneDef.count) {
                        setRecommended(`${lZone}:${lPoint + 1}`);
                    } else {
                        const zIdx = ZONES[type].findIndex(z => z.id === lZone);
                        const nextZ = ZONES[type][(zIdx + 1) % ZONES[type].length];
                        setRecommended(`${nextZ.id}:1`);
                    }
                }
            } else {
                setRecommended(`${ZONES[type][0].id}:1`);
            }
        };
        load();
    }, [type]);

    useEffect(() => {
        if (autoSelect && recommended && !selected && onSelect) {
            onSelect(recommended);
        }
    }, [recommended, autoSelect, selected, onSelect]);

    // Antigravity Patch: Allow external force of "Last Used" to bypass API delays/glitches
    useEffect(() => {
        if (forcedLastUsed) {
            setLastUsed(forcedLastUsed);
        }
    }, [forcedLastUsed]);

    const handlePointClick = async (fullId) => {
        if (onSelect) onSelect(fullId);

        // REMOVED: Immediate rotation on click causes sync issues if bolus is cancelled.
        // Rotation is now handled by the parent component (BolusPage) upon saving.
        /*
        try {
            const token = getToken();
            if (token) {
                await fetch(`${getApiBase()}/api/injection/rotate`, { ... });
            }
        } catch (e) { console.error("Failed to sync rotation", e); }
        */
    };

    const VisualComponent = type === 'rapid' ? AbdomenImageVisual : LegsImageVisual;
    const label = type === 'rapid' ? 'Rotación Abdomen' : 'Rotación Piernas/Glúteos';

    const showText = selected
        ? getLabel(type, selected)
        : (recommended ? `Recomendado: ${getLabel(type, recommended)}` : 'Selecciona un punto');

    return (
        <div className="injection-selector fade-in" style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#64748b', marginBottom: '1rem' }}>
                📍 {label}
            </div>

            <VisualComponent
                selected={selected}
                recommended={recommended}
                lastUsed={lastUsed}
                onPointClick={handlePointClick}
            />

            <div style={{ marginTop: '0.5rem', fontSize: '0.75rem', color: '#94a3b8' }}>
                {showText}
            </div>
        </div>
    );
}

// --- IMAGE VISUAL COMPONENTS ---

function AbdomenImageVisual({ selected, recommended, lastUsed, onPointClick }) {
    const getCoords = (zoneId, pointNum) => {
        let y = 58;
        if (zoneId.includes('_top')) y = 42;
        if (zoneId.includes('_mid')) y = 58;
        if (zoneId.includes('_bot')) y = 74;

        const offsets = [8, 17, 26];
        const dist = offsets[pointNum - 1];

        let x = 50;
        if (zoneId.includes('_l_')) x = 50 - dist;
        if (zoneId.includes('_r_')) x = 50 + dist;

        return { x, y };
    };

    return (
        <div style={{ position: 'relative', width: '300px', height: '300px', margin: '0 auto', borderRadius: '12px', overflow: 'hidden', boxShadow: '0 4px 10px rgba(0,0,0,0.1)' }}>
            <img
                src={assetUrl('body_abdomen.png')}
                alt="Abdomen Map"
                style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                onError={(e) => console.error("Failed to load abdomen image", e)}
            />

            <svg viewBox="0 0 100 100" style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%' }}>
                <text x="5" y="10" fontSize="4" fill="#94a3b8" fontWeight="bold">IZQ</text>
                <text x="95" y="10" fontSize="4" fill="#94a3b8" fontWeight="bold" textAnchor="end">DER</text>

                {ZONES.rapid.map(zone => (
                    Array.from({ length: zone.count }).map((_, i) => {
                        const pNum = i + 1;
                        const fullId = `${zone.id}:${pNum}`;
                        const { x, y } = getCoords(zone.id, pNum);

                        const isSel = (fullId === selected);
                        const isRec = (fullId === recommended);
                        const isLast = (fullId === lastUsed);

                        let fill = "rgba(255,255,255,0.5)";
                        let stroke = "#94a3b8";
                        let r = 2.5;
                        let sw = 0.5;

                        if (isLast) { fill = "#fecaca"; stroke = "#ef4444"; sw = 1; }
                        if (isRec) { fill = "#bbf7d0"; stroke = "#16a34a"; r = 3; sw = 1; }
                        if (isSel) { fill = "rgba(37,99,235,0.9)"; stroke = "#1e40af"; r = 4; sw = 1; }

                        return (
                            <g key={fullId} onClick={() => onPointClick(fullId)} style={{ cursor: 'pointer' }}>
                                <circle cx={x} cy={y} r="6" fill="transparent" />
                                <circle cx={x} cy={y} r={r} fill={fill} stroke={stroke} strokeWidth={sw}
                                    className={isRec && !isSel ? "pulse-animation" : ""}
                                />
                                {isSel && <text x={x} y={y + 1} fontSize="3" textAnchor="middle" fill="white" fontWeight="bold">{pNum}</text>}
                            </g>
                        );
                    })
                ))}
            </svg>

            <style>{`
        @keyframes pulse {
          0% { stroke-width: 0.5; opacity: 1; r: 3px; }
          50% { stroke-width: 2; opacity: 0.8; r: 4px; }
          100% { stroke-width: 0.5; opacity: 1; r: 3px; }
        }
        .pulse-animation rect, .pulse-animation circle { animation: pulse 2s infinite; } 
      `}</style>
        </div>
    );
}

function LegsImageVisual({ selected, recommended, lastUsed, onPointClick }) {
    const POINTS = {
        'glute_left:1': { x: 32, y: 38 },
        'glute_right:1': { x: 68, y: 38 },
        'leg_left:1': { x: 15, y: 60 },
        'leg_right:1': { x: 85, y: 60 }
    };

    return (
        <div style={{ position: 'relative', width: '300px', height: '300px', margin: '0 auto', borderRadius: '12px', overflow: 'hidden', boxShadow: '0 4px 10px rgba(0,0,0,0.1)' }}>
            <img
                src={assetUrl('body_legs.png')}
                alt="Legs/Glutes Map"
                style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                onError={(e) => console.error("Failed to load legs image", e)}
            />

            <svg viewBox="0 0 100 100" style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%' }}>
                {ZONES.basal.map(zone => {
                    const fullId = `${zone.id}:1`;
                    const pos = POINTS[fullId] || { x: 50, y: 50 };

                    const isSel = (fullId === selected);
                    const isRec = (fullId === recommended);
                    const isLast = (fullId === lastUsed);

                    let fill = "rgba(255,255,255,0.5)";
                    let stroke = "#94a3b8";
                    let r = 3;

                    if (isLast) { fill = "#fecaca"; stroke = "#ef4444"; }
                    if (isRec) { fill = "#bbf7d0"; stroke = "#16a34a"; }
                    if (isSel) { fill = "rgba(37,99,235,0.9)"; stroke = "#1e40af"; r = 5; }

                    return (
                        <g key={fullId} onClick={() => onPointClick(fullId)} style={{ cursor: 'pointer' }}>
                            <circle cx={pos.x} cy={pos.y} r={r + 4} fill="transparent" />
                            <circle cx={pos.x} cy={pos.y} r={r} fill={fill} stroke={stroke} strokeWidth="1" />
                            {isRec && !isSel && <circle cx={pos.x} cy={pos.y} r="6" fill="none" stroke="#22c55e" strokeWidth="0.5" />}
                        </g>
                    );
                })}
            </svg>
        </div>
    );
}

// HELPERS
export function saveInjectionSite(type, fullId) {
    try {
        const history = JSON.parse(localStorage.getItem('injection_history_v2') || '{}');
        history[type] = fullId;
        localStorage.setItem('injection_history_v2', JSON.stringify(history));
    } catch (e) { console.error(e); }
}

function getLabel(type, fullId) {
    if (!fullId) return '';
    const [zId, pNum] = fullId.split(':');
    const zone = ZONES[type]?.find(z => z.id === zId);
    if (!zone) return fullId;
    if (zone.count === 1) return zone.label;
    return `${zone.label} (Punto ${pNum})`;
}

export function getSiteLabel(type, fullId) {
    return getLabel(type, fullId);
}

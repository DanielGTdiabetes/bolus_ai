import React, { useState, useEffect } from 'react';

/**
 * ZONES DEFINITION & LOGIC
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

export function InjectionSiteSelector({ type, onSelect, selected }) {
    const [lastUsed, setLastUsed] = useState(null);
    const [recommended, setRecommended] = useState(null);

    // --- LOGIC: History & Recommendation ---
    useEffect(() => {
        try {
            const history = JSON.parse(localStorage.getItem('injection_history_v2') || '{}');
            const lastStr = history[type];

            if (lastStr) {
                setLastUsed(lastStr);
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
            } else {
                setRecommended(`${ZONES[type][0].id}:1`);
            }
        } catch (e) {
            console.warn("History load error", e);
        }
    }, [type]);

    useEffect(() => {
        if (recommended && !selected && onSelect) {
            onSelect(recommended);
        }
    }, [recommended]);

    const handlePointClick = (fullId) => {
        if (onSelect) onSelect(fullId);
    };

    if (type === 'rapid') {
        return (
            <div className="injection-selector fade-in" style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#64748b', marginBottom: '1rem' }}>
                    📍 Rotación Abdomen
                </div>
                <AbdomenVisual
                    selected={selected}
                    recommended={recommended}
                    lastUsed={lastUsed}
                    onPointClick={handlePointClick}
                />
                <div style={{ marginTop: '0.5rem', fontSize: '0.75rem', color: '#94a3b8' }}>
                    {selected ? getLabel('rapid', selected) : 'Selecciona un punto'}
                </div>
            </div>
        );
    }

    return (
        <div className="injection-selector fade-in" style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#64748b', marginBottom: '1rem' }}>
                📍 Rotación Piernas/Glúteos
            </div>
            <LegsVisual
                selected={selected}
                recommended={recommended}
                lastUsed={lastUsed}
                onPointClick={handlePointClick}
            />
            <div style={{ marginTop: '0.5rem', fontSize: '0.75rem', color: '#94a3b8' }}>
                {selected ? getLabel('basal', selected) : 'Selecciona un punto'}
            </div>
        </div>
    );
}

// --- VISUAL COMPONENTS (SVG AVATARS) ---

function AbdomenVisual({ selected, recommended, lastUsed, onPointClick }) {
    // We map our logical ZONES to SVG coordinates (x, y)
    // 0,0 is top-left of the viewBox
    // Torso is roughly centered. 
    // Navel at 50, 60 (width 100, height 120)

    const getCoords = (zoneId, pointNum) => {
        // Base positions relative to Navel (50, 60)
        // Left side x < 50, Right side x > 50

        let baseX = 50;
        let baseY = 60;

        // Y Offsets
        if (zoneId.includes('_top')) baseY = 35; // 5 fingers up
        if (zoneId.includes('_mid')) baseY = 60; // Navel line
        if (zoneId.includes('_bot')) baseY = 85; // Low

        // X Offsets (Inner -> Outer)
        // Left: 50 - offset. Right: 50 + offset.
        // Point 1 (Inner) ~ 15px/units away
        // Point 2 (Mid) ~ 25px
        // Point 3 (Outer) ~ 35px

        const offsets = [12, 24, 36];
        const dist = offsets[pointNum - 1]; // 0, 1, 2

        if (zoneId.includes('_l_')) baseX = 50 - dist;
        if (zoneId.includes('_r_')) baseX = 50 + dist;

        return { cx: baseX, cy: baseY };
    };

    return (
        <div style={{ position: 'relative', width: '200px', margin: '0 auto' }}>
            <svg viewBox="0 0 100 120" style={{ width: '100%', dropShadow: '0 4px 6px rgba(0,0,0,0.1)' }}>
                {/* Body Outline */}
                <path d="M 30,10 Q 20,40 25,100 L 75,100 Q 80,40 70,10 L 30,10" fill="#fce7f3" stroke="#fbcfe8" strokeWidth="2" />
                {/* Navel */}
                <circle cx="50" cy="60" r="1.5" fill="#f472b6" opacity="0.6" />
                <path d="M 48,60 Q 50,62 52,60" stroke="#f472b6" fill="none" strokeWidth="0.5" opacity="0.6" />

                {/* Grid Lines (Optional Guide) */}
                <line x1="50" y1="20" x2="50" y2="100" stroke="#fff" strokeWidth="0.5" strokeDasharray="2" opacity="0.5" />
                <line x1="25" y1="60" x2="75" y2="60" stroke="#fff" strokeWidth="0.5" strokeDasharray="2" opacity="0.5" />

                {/* Points */}
                {ZONES.rapid.map(zone => (
                    Array.from({ length: zone.count }).map((_, i) => {
                        const pNum = i + 1;
                        const fullId = `${zone.id}:${pNum}`;
                        const { cx, cy } = getCoords(zone.id, pNum);

                        const isSel = (fullId === selected);
                        const isRec = (fullId === recommended);
                        const isLast = (fullId === lastUsed);

                        let fill = "#fff";
                        let stroke = "#f9a8d4";
                        let r = 2.5;

                        if (isLast) { fill = "#fecaca"; stroke = "#ef4444"; r = 2.5; } // Red
                        if (isRec) { fill = "#bbf7d0"; stroke = "#22c55e"; r = 3; } // Green pulse
                        if (isSel) { fill = "#2563eb"; stroke = "#1d4ed8"; r = 4; } // Blue active

                        return (
                            <g key={fullId} onClick={() => onPointClick(fullId)} style={{ cursor: 'pointer' }}>
                                {/* Invisible larger target for easier clicking */}
                                <circle cx={cx} cy={cy} r="5" fill="transparent" />
                                {/* Visible Dot */}
                                <circle cx={cx} cy={cy} r={r} fill={fill} stroke={stroke} strokeWidth="1"
                                    className={isRec && !isSel ? "pulse-animation" : ""}
                                />
                                {isRec && !isSel && (
                                    <circle cx={cx} cy={cy} r={r + 2} fill="none" stroke="#22c55e" strokeWidth="0.2" opacity="0.5" />
                                )}
                            </g>
                        );
                    })
                ))}
            </svg>
            <style>{`
                @keyframes pulse {
                    0% { transform: scale(1); opacity: 1; }
                    50% { transform: scale(1.5); opacity: 0.5; }
                    100% { transform: scale(1); opacity: 1; }
                }
                .pulse-animation___ { animation: pulse 2s infinite; } 
            `}</style>
        </div>
    );
}

function LegsVisual({ selected, recommended, lastUsed, onPointClick }) {
    // Simple Legs/Thighs/Glutes
    // ViewBox 0 0 100 120
    const POINTS = {
        'leg_left:1': { cx: 35, cy: 70 },
        'leg_right:1': { cx: 65, cy: 70 },
        'glute_left:1': { cx: 30, cy: 40 }, // Back view conceptually
        'glute_right:1': { cx: 70, cy: 40 }
    };

    return (
        <div style={{ position: 'relative', width: '150px', margin: '0 auto' }}>
            <svg viewBox="0 0 100 120" style={{ width: '100%' }}>
                {/* Legs Outline (Front/Back Hybrid for simplicity) */}
                <path d="M 20,40 Q 15,60 25,110 L 45,110 L 50,60 L 55,110 L 75,110 Q 85,60 80,40 Q 50,30 20,40" fill="#f1f5f9" stroke="#94a3b8" strokeWidth="1" />
                {/* Glute lines */}
                <path d="M 50,60 Q 30,55 20,40" fill="none" stroke="#cbd5e1" strokeWidth="0.5" />
                <path d="M 50,60 Q 70,55 80,40" fill="none" stroke="#cbd5e1" strokeWidth="0.5" />

                {ZONES.basal.map(zone => {
                    const fullId = `${zone.id}:1`;
                    const pos = POINTS[fullId] || { cx: 50, cy: 50 };

                    const isSel = (fullId === selected);
                    const isRec = (fullId === recommended);
                    const isLast = (fullId === lastUsed);

                    let fill = "#cbd5e1";
                    let stroke = "#94a3b8";
                    let r = 4;

                    if (isLast) { fill = "#fecaca"; stroke = "#ef4444"; }
                    if (isRec) { fill = "#bbf7d0"; stroke = "#22c55e"; }
                    if (isSel) { fill = "#2563eb"; stroke = "#1d4ed8"; r = 5; }

                    return (
                        <g key={fullId} onClick={() => onPointClick(fullId)} style={{ cursor: 'pointer' }}>
                            <circle cx={pos.cx} cy={pos.cy} r={r} fill={fill} stroke={stroke} strokeWidth="1" />
                            {isRec && !isSel && <circle cx={pos.cx} cy={pos.cy} r="7" fill="none" stroke="#22c55e" strokeWidth="0.5" />}
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

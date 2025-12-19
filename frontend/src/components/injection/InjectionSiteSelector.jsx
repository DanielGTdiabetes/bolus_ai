import React, { useState, useEffect } from 'react';

/**
 * ZONES DEFINITION CUSTOMIZED
 */

const ZONES = {
    rapid: [
        // LEFT SIDE (User Left)
        { id: 'abd_l_top', label: 'Abd. Izq - Arriba', count: 3 },
        { id: 'abd_l_mid', label: 'Abd. Izq - Medio', count: 3 },
        { id: 'abd_l_bot', label: 'Abd. Izq - Bajo', count: 3 },
        // RIGHT SIDE (User Right)
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
                <AbdomenImageVisual
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
                📍 Rotación Piernas/Gluesto
            </div>
            <LegsImageVisual
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

// --- IMAGE VISUAL COMPONENTS ---

function AbdomenImageVisual({ selected, recommended, lastUsed, onPointClick }) {
    // 300x300 container
    // Image is centered. We overlay SVGs points.

    // Coordinates mapping for "body_abdomen.png"
    // Assuming image is centered perfectly.
    // X center = 50%. 
    // Y center approx mid.

    const getCoords = (zoneId, pointNum) => {
        // Percentages relative to container
        let y = 60; // Mid
        if (zoneId.includes('_top')) y = 40;
        if (zoneId.includes('_mid')) y = 60;
        if (zoneId.includes('_bot')) y = 80;

        // X Spacing from Center (50)
        // P1: 10% dist, P2: 20%, P3: 30%
        const offsets = [10, 20, 30];
        const dist = offsets[pointNum - 1];

        let x = 50;
        if (zoneId.includes('_l_')) x = 50 - dist;
        if (zoneId.includes('_r_')) x = 50 + dist;

        return { x, y };
    };

    return (
        <div style={{ position: 'relative', width: '300px', height: '300px', margin: '0 auto', borderRadius: '12px', overflow: 'hidden', boxShadow: '0 4px 10px rgba(0,0,0,0.1)' }}>
            <img
                src="./body_abdomen.png"
                alt="Abdomen Map"
                style={{ width: '100%', height: '100%', objectFit: 'cover' }}
            />

            {/* Overlay SVG Layer */}
            <svg viewBox="0 0 100 100" style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%' }}>
                {/* Labels */}
                <text x="10" y="10" fontSize="4" fill="#94a3b8" fontWeight="bold">IZQ</text>
                <text x="90" y="10" fontSize="4" fill="#94a3b8" fontWeight="bold" textAnchor="end">DER</text>

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
                        if (isSel) { fill = "#2563eb"; stroke = "#1e40af"; r = 4; sw = 1; fill = "rgba(37,99,235,0.9)"; }

                        return (
                            <g key={fullId} onClick={() => onPointClick(fullId)} style={{ cursor: 'pointer' }}>
                                {/* Invisible larger target */}
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
    // 300x300
    // The generated image has 2 panels (Front Thighs | Back Glutes) side by side.
    // So X: 0-50% is Thighs, 50-100% is Glutes.

    // Thighs (Left Panel): Left Leg (x~15), Right Leg (x~35)
    // Glutes (Right Panel): Left Glute (x~65), Right Glute (x~85)

    const POINTS = {
        'leg_left:1': { x: 18, y: 55 },
        'leg_right:1': { x: 32, y: 55 },
        'glute_left:1': { x: 68, y: 50 },
        'glute_right:1': { x: 82, y: 50 }
    };

    return (
        <div style={{ position: 'relative', width: '300px', height: '300px', margin: '0 auto', borderRadius: '12px', overflow: 'hidden', boxShadow: '0 4px 10px rgba(0,0,0,0.1)' }}>
            <img
                src="./body_legs.png"
                alt="Legs/Glutes Map"
                style={{ width: '100%', height: '100%', objectFit: 'cover' }}
            />

            <svg viewBox="0 0 100 100" style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%' }}>
                {/* Labels */}
                <text x="25" y="10" fontSize="4" fill="#64748b" textAnchor="middle" fontWeight="bold">MUSLOS</text>
                <text x="75" y="10" fontSize="4" fill="#64748b" textAnchor="middle" fontWeight="bold">GLÚTEOS</text>

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
                    if (isSel) { fill = "#2563eb"; stroke = "#1e40af"; r = 5; fill = "rgba(37,99,235,0.9)"; }

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

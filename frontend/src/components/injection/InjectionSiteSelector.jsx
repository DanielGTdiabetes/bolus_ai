import React, { useState, useEffect } from 'react';

/**
 * ZONES DEFINITION CUSTOMIZED
 * Per user logic:
 * Abd (Rapid): Left/Right -> 3 Rows -> 3 Points each. Total 18 points.
 * To simplify UI, we will group them by Regions (Left/Right) and Rows (Top/Mid/Low).
 * Inside each block, we rotate 1->2->3.
 */

const ZONES = {
    rapid: [
        // LEFT SIDE
        { id: 'abd_l_top', label: 'Abd. Izq - Arriba', count: 3 },
        { id: 'abd_l_mid', label: 'Abd. Izq - Medio', count: 3 },
        { id: 'abd_l_bot', label: 'Abd. Izq - Bajo', count: 3 },
        // RIGHT SIDE
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

// Logic:
// 1. We track "zone_id" + "point_index" (1, 2, 3).
// 2. If user was on Point 1, next suggestion is Point 2 SAME ZONE.
// 3. If user was on Point 3 (last), move to NEXT ZONE, Point 1.

export function InjectionSiteSelector({ type, onSelect, selected }) {
    // State stores object: { zoneId: 'abd_l_top', point: 1 }
    // But props only pass a string ID for 'selected'. 
    // We need to encode Point into the ID string like "abd_l_top:1"

    const [lastUsed, setLastUsed] = useState(null); // String "id:point"
    const [recommended, setRecommended] = useState(null); // String "id:point"

    useEffect(() => {
        try {
            const history = JSON.parse(localStorage.getItem('injection_history_v2') || '{}');
            const lastStr = history[type]; // e.g. "abd_l_top:2"

            if (lastStr) {
                setLastUsed(lastStr);
                const [lZone, lPointStr] = lastStr.split(':');
                const lPoint = parseInt(lPointStr);

                const zoneDef = ZONES[type].find(z => z.id === lZone);

                if (zoneDef && lPoint < zoneDef.count) {
                    // Move to next point in same zone
                    setRecommended(`${lZone}:${lPoint + 1}`);
                } else {
                    // Move to next zone, point 1
                    const zIdx = ZONES[type].findIndex(z => z.id === lZone);
                    const nextZ = ZONES[type][(zIdx + 1) % ZONES[type].length];
                    setRecommended(`${nextZ.id}:1`);
                }

            } else {
                // Default Start: Top Left Point 1
                setRecommended(`${ZONES[type][0].id}:1`);
            }
        } catch (e) {
            console.warn("History load error", e);
        }
    }, [type]);

    // Auto-select
    useEffect(() => {
        if (recommended && !selected && onSelect) {
            onSelect(recommended);
        }
    }, [recommended]);

    const handleSelect = (fullId) => {
        if (onSelect) onSelect(fullId);
    };

    const zonesToShow = ZONES[type] || ZONES.rapid;
    const isRapid = type === 'rapid'; // Only rapid has the complex 3-point grid

    return (
        <div className="injection-selector fade-in">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                <span style={{ fontSize: '0.85rem', fontWeight: 600, color: '#64748b' }}>
                    📍 Rotación ({isRapid ? 'Abdomen 3x3' : 'Muslos/Glúteos'})
                </span>
                {lastUsed && (
                    <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                        Último: {getLabel(type, lastUsed)}
                    </span>
                )}
            </div>

            <div style={{
                display: 'grid',
                gridTemplateColumns: isRapid ? '1fr 1fr' : '1fr 1fr',
                gap: '8px'
            }}>
                {zonesToShow.map(zone => {
                    // For each zone, we render a box.
                    // If complex (count > 1), we show dots inside.

                    const [selZone, selPoint] = (selected || '').split(':');
                    const [recZone, recPoint] = (recommended || '').split(':');
                    const [lastZone, lastPoint] = (lastUsed || '').split(':');

                    const isActiveZone = (selZone === zone.id);

                    return (
                        <div key={zone.id} style={{
                            background: '#f8fafc',
                            border: isActiveZone ? '1px solid var(--primary)' : '1px solid #e2e8f0',
                            borderRadius: '8px',
                            padding: '0.5rem',
                            position: 'relative'
                        }}>
                            <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#64748b', marginBottom: '4px', textAlign: 'center' }}>
                                {zone.label.replace('Abd. ', '')}
                            </div>

                            <div style={{ display: 'flex', justifyContent: 'center', gap: '8px' }}>
                                {Array.from({ length: zone.count }).map((_, i) => {
                                    const pNum = i + 1;
                                    const fullId = `${zone.id}:${pNum}`;

                                    const isSel = (fullId === selected);
                                    const isRec = (fullId === recommended);
                                    const isLast = (fullId === lastUsed);

                                    let bg = '#e2e8f0';
                                    let border = '1px solid #cbd5e1';

                                    if (isLast) { bg = '#fecaca'; border = '1px solid #ef4444'; }
                                    if (isRec) { bg = '#bbf7d0'; border = '1px solid #22c55e'; }
                                    if (isSel) { bg = 'var(--primary)'; border = '1px solid #1d4ed8'; }

                                    return (
                                        <button
                                            key={pNum}
                                            onClick={() => handleSelect(fullId)}
                                            style={{
                                                width: '24px', height: '24px', borderRadius: '50%',
                                                background: bg, border: border,
                                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                                fontSize: '0.7rem', fontWeight: 700,
                                                color: isSel ? '#fff' : '#334155',
                                                cursor: 'pointer', position: 'relative'
                                            }}
                                        >
                                            {pNum}
                                            {isRec && !isSel && <div style={{ position: 'absolute', top: -4, right: -4, width: 8, height: 8, borderRadius: '50%', background: 'green' }} />}
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    );
                })}
            </div>
            <div style={{ marginTop: '0.5rem', fontSize: '0.75rem', color: '#64748b', lineHeight: 1.4 }}>
                * Puntos 1 (Interior), 2 (Medio), 3 (Exterior).
            </div>
        </div>
    );
}

// Helpers
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


import React, { useState, useEffect } from 'react';
import { getCalcParams } from '../../modules/core/store';

export function PreBolusTimer() {
    const [waitMin, setWaitMin] = useState(0);
    const [eatTime, setEatTime] = useState(null);
    const [name, setName] = useState("");

    useEffect(() => {
        // Can read directly since store is synchronous for getCalcParams usually, 
        // but let's keep it safe.
        const p = getCalcParams();
        const min = p?.insulin?.pre_bolus_min || 0;
        setWaitMin(min);
        setName(p?.insulin?.name || "");

        if (min > 0) {
            const now = new Date();
            const eatAt = new Date(now.getTime() + min * 60000);
            setEatTime(eatAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
        }
    }, []);

    if (waitMin <= 0) return null;

    return (
        <div style={{ textAlign: 'center', marginBottom: '1rem' }}>
            <div style={{
                background: '#e0f2fe',
                color: '#0369a1',
                padding: '0.6rem 1rem',
                borderRadius: '20px',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '8px',
                fontSize: '0.9rem',
                fontWeight: 600,
                border: '1px solid #bae6fd'
            }}>
                <span>⏳ Espera {waitMin} min {name ? `(${name})` : ''}</span>
                {eatTime && <span style={{ opacity: 0.8, fontWeight: 400 }}>→ Comer a las {eatTime}</span>}
            </div>
        </div>
    );
}

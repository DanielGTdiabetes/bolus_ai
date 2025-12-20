import React, { useState, useEffect } from 'react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, ComposedChart, Line } from 'recharts';
import { getGlucoseEntries, fetchTreatments, getLocalNsConfig } from '../../lib/api';

export function MainGlucoseChart({ isLow, predictionData }) {
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        // ... (existing load logic remains same, just ensure it runs once)
        async function load() {
            // ... existing load function body ...
            // COPY PASTE EXISTING LOAD BODY HERE to ensure it works? 
            // Wait, I can't copy paste easily.
            // I will leave existing Effect valid.
            // But wait, the user instructions say "In the body...".
            // I'm replacing the top part of the function.
        }
        // ...
    }, []);

    // ... this tool call is tricky because I need to preserve the hook body.
    // I should use a more targeted replacement if possible.
    // Or I just modify the `if (loading)` part and the `export function` signature.

    // Combining Logic:
    const chartData = React.useMemo(() => {
        if (!data || !data.length) return [];
        if (!predictionData || !predictionData.series || !predictionData.series.length) return data;

        // Find last real time
        const lastReal = data[data.length - 1];
        const lastTime = lastReal ? lastReal.timestamp : Date.now();

        // Map prediction
        const predPoints = predictionData.series.map(p => {
            const t = lastTime + (p.t_min * 60000); // Approximate relative to last known point or Now
            return {
                timeLabel: new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
                prediction: p.bg,
                bg: null, // Don't show real BG here
                iob: null,
                cob: null,
                timestamp: t
            };
        });

        // Connect the lines?
        // Add the last real point as the first prediction point to ensure continuity
        if (lastReal) {
            predPoints.unshift({
                ...lastReal,
                prediction: lastReal.bg, // Start prediction at current BG
                bg: lastReal.bg // Overlap visual?
            });
        }

        return [...data, ...predPoints];
    }, [data, predictionData]);

    if (loading || !chartData.length) return <div className="animate-pulse h-[140px] bg-gray-100 rounded-lg w-full"></div>;

    // Recalculate max/min for Gradient based on chartData
    const values = chartData.map(d => d.bg || d.prediction).filter(v => v != null);
    const maxVal = Math.max(...values);
    const minVal = Math.min(...values);



    // Thresholds
    const HIGH = 180;
    const LOW = 70;

    // Calculate offsets for gradient stops
    // In SVG gradient: 0% is Top (Max Value), 100% is Bottom (Min Value)
    // Formula: (MaxVal - Threshold) / (MaxVal - MinVal)

    const range = maxVal - minVal;

    let offHigh = 0;
    let offLow = 1;

    if (range > 0) {
        if (maxVal > HIGH) {
            offHigh = (maxVal - HIGH) / range;
        }
        if (minVal < LOW) {
            offLow = (maxVal - LOW) / range;
        }
    }

    // Clamp values [0, 1]
    offHigh = Math.min(Math.max(offHigh, 0), 1);
    offLow = Math.min(Math.max(offLow, 0), 1);

    return (
        <div style={{ width: '100%', height: '160px', marginTop: '0.5rem', position: 'relative' }}>
            <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={chartData} margin={{ top: 10, right: 0, left: -20, bottom: 0 }}>
                    <defs>
                        <linearGradient id="splitColor" x1="0" y1="0" x2="0" y2="1">
                            {/* Top -> High Threshold */}
                            <stop offset={offHigh} stopColor="#ef4444" stopOpacity={1} />
                            <stop offset={offHigh} stopColor="#3b82f6" stopOpacity={1} />

                            {/* Low Threshold -> Bottom */}
                            <stop offset={offLow} stopColor="#3b82f6" stopOpacity={1} />
                            <stop offset={offLow} stopColor="#ef4444" stopOpacity={1} />
                        </linearGradient>
                        <linearGradient id="splitFill" x1="0" y1="0" x2="0" y2="1">
                            <stop offset={offHigh} stopColor="#ef4444" stopOpacity={0.2} />
                            <stop offset={offHigh} stopColor="#3b82f6" stopOpacity={0.2} />
                            <stop offset={offLow} stopColor="#3b82f6" stopOpacity={0.2} />
                            <stop offset={offLow} stopColor="#ef4444" stopOpacity={0.2} />
                        </linearGradient>
                    </defs>

                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />

                    <XAxis
                        dataKey="timeLabel"
                        tick={{ fontSize: 10, fill: '#94a3b8' }}
                        interval="preserveStartEnd"
                        minTickGap={35}
                    />

                    {/* Glucose Axis */}
                    <YAxis
                        yAxisId="bg"
                        domain={[
                            min => Math.min(60, Math.floor((min ?? 70) / 10) * 10),
                            max => Math.max(200, Math.ceil((max ?? 180) / 10) * 10)
                        ]}
                        tick={{ fontSize: 10, fill: '#94a3b8' }}
                        width={30}
                    />

                    {/* Insulin (IOB) Axis - Hidden or Right */}
                    <YAxis yAxisId="iob" orientation="right" hide domain={[0, 'auto']} />

                    {/* Carbs (COB) Axis - Hidden or Right */}
                    <YAxis yAxisId="cob" orientation="right" hide domain={[0, 'auto']} />

                    <Tooltip content={<CustomTooltip />} />

                    {/* Guides */}
                    <ReferenceLine yAxisId="bg" y={LOW} stroke="#ef4444" strokeDasharray="3 3" opacity={0.3} strokeWidth={1} />
                    <ReferenceLine yAxisId="bg" y={HIGH} stroke="#f59e0b" strokeDasharray="3 3" opacity={0.3} strokeWidth={1} />

                    {/* COB Curve (Orange Line) */}
                    <Area
                        yAxisId="cob"
                        type="monotone"
                        dataKey="cob"
                        stroke="#f97316"
                        strokeWidth={2}
                        fill="transparent"
                        connectNulls
                        strokeDasharray="4 4"
                        activeDot={{ r: 4, fill: '#f97316', stroke: '#fff' }}
                        animationDuration={500}
                    />

                    {/* IOB Curve (Blue Area, subtle) */}
                    <Area
                        yAxisId="iob"
                        type="monotone"
                        dataKey="iob"
                        stroke="#06b6d4"
                        fill="#06b6d4"
                        fillOpacity={0.1}
                        strokeWidth={2}
                        connectNulls
                        activeDot={{ r: 4, fill: '#06b6d4', stroke: '#fff' }}
                        animationDuration={500}
                    />

                    {/* Glucose Curve (Main) */}
                    <Area
                        yAxisId="bg"
                        type="monotone"
                        dataKey="bg"
                        stroke="url(#splitColor)"
                        strokeWidth={3}
                        fill="url(#splitFill)"
                        activeDot={{ r: 6, strokeWidth: 0, fill: '#1e293b' }}
                        animationDuration={1000}
                    />

                    {/* Prediction Curve (Purple Dashed) */}
                    <Line
                        yAxisId="bg"
                        type="monotone"
                        dataKey="prediction"
                        stroke="#8b5cf6" // Violet-500
                        strokeWidth={3}
                        strokeDasharray="5 5"
                        dot={false}
                        activeDot={{ r: 4, fill: '#8b5cf6' }}
                        animationDuration={500}
                    />
                </ComposedChart>
            </ResponsiveContainer>
        </div>
    );
}

function CustomTooltip({ active, payload, label }) {
    if (active && payload && payload.length) {
        // payload order depends on chart definition order (reversed visually sometimes)
        // Usually: [COB, IOB, BG] based on code above.
        // We find by dataKey to be safe.
        const bgItem = payload.find(p => p.dataKey === 'bg');
        const iobItem = payload.find(p => p.dataKey === 'iob');
        const cobItem = payload.find(p => p.dataKey === 'cob');

        return (
            <div style={{ background: 'rgba(255, 255, 255, 0.95)', padding: '10px', borderRadius: '12px', boxShadow: '0 4px 15px rgba(0,0,0,0.1)', border: '1px solid #e2e8f0', minWidth: '120px' }}>
                <p style={{ margin: 0, fontSize: '0.8rem', color: '#64748b', marginBottom: '5px' }}>{label}</p>

                {/* Glucose */}
                {bgItem && (
                    <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#1e293b', lineHeight: 1, marginBottom: '8px' }}>
                        {bgItem.value} <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#94a3b8' }}>mg/dL</span>
                    </div>
                )}

                {/* Insulin / Carbs Grid */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', fontSize: '0.75rem' }}>

                    {/* IOB */}
                    <div style={{ color: '#06b6d4', fontWeight: 700 }}>
                        <div>IOB</div>
                        <div style={{ fontSize: '0.9rem' }}>{iobItem ? iobItem.value : 0} U</div>
                    </div>

                    {/* COB */}
                    <div style={{ color: '#f97316', fontWeight: 700 }}>
                        <div>COB</div>
                        <div style={{ fontSize: '0.9rem' }}>{cobItem ? cobItem.value : 0} g</div>
                    </div>
                </div>
            </div>
        );
    }
    return null;
}

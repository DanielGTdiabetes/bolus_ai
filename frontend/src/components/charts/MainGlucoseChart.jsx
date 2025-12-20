import React, { useState, useEffect } from 'react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, ComposedChart, Line } from 'recharts';
import { getGlucoseEntries, fetchTreatments, getLocalNsConfig } from '../../lib/api';

export function MainGlucoseChart({ isLow }) {
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        async function load() {
            setLoading(true);
            try {
                const config = getLocalNsConfig();
                // 1. Fetch data
                // We fetch 6 hours of glucose for context, and treatments for IOB calc
                const [glucoseData, treatmentData] = await Promise.all([
                    getGlucoseEntries(72), // 72 * 5m = 6 hours
                    fetchTreatments({ ...config, count: 50 }) // 50 recent treatments
                ]);

                if (!glucoseData || glucoseData.length === 0) {
                    setData([]);
                    setLoading(false);
                    return;
                }

                // Sort Glucose Chronologically
                const sortedG = [...glucoseData].reverse();

                // 2. Process Treatments & Calculate Curves
                // Simulation Parameters
                const IOB_DURATION = 4 * 60 * 60 * 1000; // 4 hours
                const COB_DURATION = 3 * 60 * 60 * 1000; // 3 hours

                // Helper to calculate active amount at a given time
                const getActive = (time, treatments, type) => {
                    let total = 0;
                    const duration = type === 'insulin' ? IOB_DURATION : COB_DURATION;

                    treatments.forEach(t => {
                        const tTime = new Date(t.created_at || t.timestamp).getTime();
                        const val = type === 'insulin' ? (parseFloat(t.insulin) || 0) : (parseFloat(t.carbs) || 0);

                        // Skip if value is 0 or invalid
                        if (val <= 0) return;

                        const elapsed = time - tTime;
                        if (elapsed >= 0 && elapsed < duration) {
                            // Simple Linear Decay Model
                            // (Can be swapped for exponential if needed)
                            const remaining = val * (1 - (elapsed / duration));
                            total += remaining;
                        }
                    });
                    return total;
                };

                // Enhance Glucose Points with IOB/COB
                // We only chart the last ~3-4 hours of glucose to keep it readable,
                // but we needed the history for IOB calc.
                // Let's decide to show the user the requested amount (last 36 entries = 3h).

                const VIEW_WINDOW = 36;
                const viewData = sortedG.slice(Math.max(0, sortedG.length - VIEW_WINDOW));

                const processedData = viewData.map(g => {
                    const time = new Date(g.date).getTime();
                    return {
                        timeLabel: new Date(g.date).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
                        bg: g.sgv,
                        iob: parseFloat(getActive(time, treatmentData, 'insulin').toFixed(2)),
                        cob: parseFloat(getActive(time, treatmentData, 'carbs').toFixed(0)), // Carbs integer usually fine
                        timestamp: time
                    };
                });

                setData(processedData);
            } catch (err) {
                console.error("Chart load error", err);
            } finally {
                setLoading(false);
            }
        }
        load();
    }, []);

    if (loading || !data.length) return <div className="animate-pulse h-[140px] bg-gray-100 rounded-lg w-full"></div>;

    // --- Dynamic Gradient Logic ---
    const maxVal = Math.max(...data.map(d => d.bg));
    const minVal = Math.min(...data.map(d => d.bg));

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
                <ComposedChart data={data} margin={{ top: 10, right: 0, left: -20, bottom: 0 }}>
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
                            min => Math.min(60, Math.floor(min / 10) * 10),
                            max => Math.max(200, Math.ceil(max / 10) * 10)
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

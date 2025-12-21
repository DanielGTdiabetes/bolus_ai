import React, { useState, useEffect } from 'react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, ComposedChart, Line } from 'recharts';
import { getGlucoseEntries, getLocalNsConfig } from '../../lib/api';

export function MainGlucoseChart({ isLow, predictionData }) {
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let mounted = true;
        async function load() {
            try {
                const config = getLocalNsConfig();
                // Fetch simple glucose history (24h or so, but let's limit to recent reasonable window for chart)
                // Assuming getGlucoseEntries handles basic fetch.
                const entries = await getGlucoseEntries(config);

                if (mounted) {
                    if (entries && entries.length > 0) {
                        // Map Nightscout/API entries to Chart Data
                        // API returns newest first usually. Reverse for chart (Time ascending).
                        const sorted = [...entries].sort((a, b) => a.date - b.date);

                        // Filter to last 6 hours to match forecast context usually
                        const now = Date.now();
                        const cutoff = now - (6 * 60 * 60 * 1000);
                        const recent = sorted.filter(e => e.date > cutoff);

                        const mapped = recent.map(e => ({
                            timestamp: e.date,
                            timeLabel: new Date(e.date).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
                            bg: e.sgv,
                            iob: null, // Complex IOB history calc skipped for stability
                            cob: null
                        }));
                        setData(mapped);
                    } else {
                        setData([]);
                    }
                }
            } catch (e) {
                console.warn("Chart Load Error", e);
            } finally {
                if (mounted) setLoading(false);
            }
        }
        load();
        return () => { mounted = false; };
    }, []);

    // Combining Logic: Historical + Prediction
    const chartData = React.useMemo(() => {
        // If no history, we can still show prediction if available
        let baseData = data || [];

        if (!predictionData || !predictionData.series || !predictionData.series.length) {
            return baseData;
        }

        // Determine start time for prediction
        let lastTime = Date.now();
        let startBg = 120; // fallback

        if (baseData.length > 0) {
            const lastPoint = baseData[baseData.length - 1];
            lastTime = lastPoint.timestamp;
            startBg = lastPoint.bg;
        } else if (predictionData.summary && predictionData.summary.bg_now) {
            startBg = predictionData.summary.bg_now;
        }

        // Map prediction series
        const predPoints = predictionData.series.map(p => {
            // p.t_min is relative minutes from "now" (or start of sim)
            const t = lastTime + (p.t_min * 60000);

            // Resolve components if available
            let cCurve = null;
            let iCurve = null;

            if (predictionData.components) {
                const comp = predictionData.components.find(c => c.t_min === p.t_min);
                if (comp) {
                    // StartBG + Impact shows "what if only this existed" relative to start
                    cCurve = startBg + (comp.carb_impact || 0);
                    iCurve = startBg + (comp.insulin_impact || 0);
                }
            }

            return {
                timeLabel: new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
                prediction: p.bg,
                bg: null,
                carbCurve: cCurve,
                insulinCurve: iCurve,
                timestamp: t
            };
        });

        // Stitching: Add the last real point as the start of prediction for continuity
        if (baseData.length > 0) {
            const lastReal = baseData[baseData.length - 1];
            predPoints.unshift({
                ...lastReal,
                prediction: lastReal.bg, // Start prediction curve at actual BG
                carbCurve: lastReal.bg, // Start component curves at actual BG
                insulinCurve: lastReal.bg,
                bg: null // Don't duplicate the 'Area' point, just start the 'Line'
            });
        }

        return [...baseData, ...predPoints];
    }, [data, predictionData]);

    if (loading) return <div className="animate-pulse h-[140px] bg-gray-100 rounded-lg w-full"></div>;
    // Allow empty chart if no data but loaded
    if (!chartData.length) return <div className="text-center text-xs text-gray-400 py-10">Sin datos de glucosa</div>;

    // Recalculate max/min for domain
    const allValues = chartData.flatMap(d => [d.bg, d.prediction]).filter(v => v != null && !isNaN(v));
    const maxVal = allValues.length ? Math.max(...allValues) : 180;
    const minVal = allValues.length ? Math.min(...allValues) : 70;

    // Gradient Thresholds
    const HIGH = 180;
    const LOW = 70;
    const range = maxVal - minVal;
    let offHigh = 0;
    let offLow = 1;

    if (range > 0) {
        if (maxVal > HIGH) offHigh = (maxVal - HIGH) / range;
        if (minVal < LOW) offLow = (maxVal - LOW) / range;
    }
    offHigh = Math.min(Math.max(offHigh, 0), 1);
    offLow = Math.min(Math.max(offLow, 0), 1);

    return (
        <div style={{ width: '100%', height: '100%', minHeight: '160px', marginTop: '0.5rem', position: 'relative' }}>
            <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={chartData} margin={{ top: 10, right: 0, left: -10, bottom: 0 }}>
                    <defs>
                        <linearGradient id="splitColor" x1="0" y1="0" x2="0" y2="1">
                            <stop offset={offHigh} stopColor="#ef4444" stopOpacity={1} />
                            <stop offset={offHigh} stopColor="#3b82f6" stopOpacity={1} />
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

                    <YAxis
                        yAxisId="bg"
                        domain={[
                            min => Math.min(60, Math.floor((minVal ?? 70) / 10) * 10),
                            max => Math.max(200, Math.ceil((maxVal ?? 180) / 10) * 10)
                        ]}
                        tick={{ fontSize: 10, fill: '#94a3b8' }}
                        width={30}
                    />

                    <Tooltip content={<CustomTooltip />} />

                    <ReferenceLine yAxisId="bg" y={LOW} stroke="#ef4444" strokeDasharray="3 3" opacity={0.3} strokeWidth={1} />
                    <ReferenceLine yAxisId="bg" y={HIGH} stroke="#f59e0b" strokeDasharray="3 3" opacity={0.3} strokeWidth={1} />

                    {/* Historical BG */}
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

                    {/* Prediction Curve */}
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

                    {/* Component Curves (Optional) */}
                    {chartData.some(d => d.carbCurve) && (
                        <Line
                            yAxisId="bg"
                            type="monotone"
                            dataKey="carbCurve"
                            stroke="#f59e0b" // Amber/Orange for Carbs
                            strokeWidth={2}
                            strokeDasharray="3 3"
                            dot={false}
                            animationDuration={500}
                            name="Carbohidratos"
                        />
                    )}
                    {chartData.some(d => d.insulinCurve) && (
                        <Line
                            yAxisId="bg"
                            type="monotone"
                            dataKey="insulinCurve"
                            stroke="#06b6d4" // Cyan for Insulin
                            strokeWidth={2}
                            strokeDasharray="3 3"
                            dot={false}
                            animationDuration={500}
                            name="Insulina"
                        />
                    )}
                </ComposedChart>
            </ResponsiveContainer>
        </div>
    );
}

function CustomTooltip({ active, payload, label }) {
    if (active && payload && payload.length) {
        const bgItem = payload.find(p => p.dataKey === 'bg');
        const predItem = payload.find(p => p.dataKey === 'prediction');

        // Prioritize actual BG, else show prediction
        const val = bgItem?.value ?? predItem?.value;
        const isPred = !bgItem?.value && predItem?.value;

        return (
            <div style={{ background: 'rgba(255, 255, 255, 0.95)', padding: '10px', borderRadius: '12px', boxShadow: '0 4px 15px rgba(0,0,0,0.1)', border: '1px solid #e2e8f0', minWidth: '120px' }}>
                <p style={{ margin: 0, fontSize: '0.8rem', color: '#64748b', marginBottom: '5px' }}>
                    {label} {isPred && <span style={{ color: '#8b5cf6' }}>(Est.)</span>}
                </p>

                <div style={{ fontSize: '1.2rem', fontWeight: 800, color: isPred ? '#8b5cf6' : '#1e293b', lineHeight: 1, marginBottom: '8px' }}>
                    {Math.round(val || 0)} <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#94a3b8' }}>mg/dL</span>
                </div>
            </div>
        );
    }
    return null;
}

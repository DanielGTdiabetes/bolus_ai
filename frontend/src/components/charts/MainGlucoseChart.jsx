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
                // Fetch simple glucose history (24h to ensure full coverage for 6h chart)
                const entries = await getGlucoseEntries(288);

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

            // Resolve baseline (ghost) curve if available
            let bVal = null;
            if (predictionData.baseline_series) {
                // Find matching point by t_min. Usually index matches but safe find is better.
                const bPoint = predictionData.baseline_series.find(b => b.t_min === p.t_min);
                if (bPoint) bVal = bPoint.bg;
            }

            return {
                timeLabel: new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
                prediction: p.bg,
                baselinePrediction: bVal,
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
                baselinePrediction: lastReal.bg, // Start ghost curve at actual BG
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

    // FIX: If values are strictly within safe range, avoid gradient to prevent glitches
    // This solves the issue of red dots appearing when the line is perfectly fine but gradient math is unstable
    const isSafe = minVal >= LOW && maxVal <= HIGH;
    const strokeColor = isSafe ? '#3b82f6' : 'url(#splitColor)';
    const fillColor = isSafe ? 'rgba(59, 130, 246, 0.2)' : 'url(#splitFill)';

    const nightPatternApplied = Boolean(predictionData?.prediction_meta?.pattern?.applied);

    return (
        <div style={{ width: '100%', height: '100%', minHeight: '160px', marginTop: '0.5rem', position: 'relative' }}>
            {nightPatternApplied && (
                <div
                    title="Ajuste basado en tu patrón nocturno (00:00–03:45). Se desactiva si hay digestión lenta o datos incompletos."
                    style={{
                        position: 'absolute',
                        top: '4px',
                        right: '8px',
                        background: '#f1f5f9',
                        color: '#475569',
                        fontSize: '0.7rem',
                        fontWeight: 600,
                        padding: '2px 6px',
                        borderRadius: '999px',
                        border: '1px solid #e2e8f0',
                        zIndex: 2
                    }}
                >
                    Patrón nocturno
                </div>
            )}
            <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
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
                        allowDataOverflow={true}
                        tick={{ fontSize: 10, fill: '#94a3b8' }}
                        width={40}
                    />

                    <Tooltip
                        content={<CustomTooltip />}
                        cursor={{ stroke: '#94a3b8', strokeWidth: 1, strokeDasharray: '3 3' }}
                    />

                    <ReferenceLine yAxisId="bg" y={LOW} stroke="#ef4444" strokeDasharray="3 3" opacity={0.3} strokeWidth={1} />
                    <ReferenceLine yAxisId="bg" y={HIGH} stroke="#f59e0b" strokeDasharray="3 3" opacity={0.3} strokeWidth={1} />

                    {/* Historical BG */}
                    <Area
                        yAxisId="bg"
                        type="monotone"
                        dataKey="bg"
                        stroke={strokeColor}
                        strokeWidth={3}
                        fill={fillColor}
                        activeDot={{ r: 6, strokeWidth: 0, fill: '#1e293b' }}
                        animationDuration={1000}
                    />

                    {/* Baseline / Risk Curve (Ghost) */}
                    {chartData.some(d => d.baselinePrediction) && (
                        <Line
                            yAxisId="bg"
                            type="monotone"
                            dataKey="baselinePrediction"
                            stroke="#94a3b8" // Slate-400 (Ghost)
                            strokeWidth={2}
                            strokeDasharray="2 2"
                            opacity={0.7}
                            dot={false}
                            animationDuration={0}
                            name="Sin acción"
                        />
                    )}

                    {/* Prediction Curve */}
                    <Line
                        yAxisId="bg"
                        type="monotone"
                        dataKey="prediction"
                        stroke={predictionData?.slow_absorption_active ? "#f59e0b" : "#8b5cf6"} // Amber-500 if slow, else Violet-500
                        strokeWidth={3}
                        strokeDasharray={predictionData?.slow_absorption_active ? "0" : "5 5"} // Solid line if slow (more certain/modelled-heavy)
                        dot={false}
                        activeDot={{ r: 4, fill: predictionData?.slow_absorption_active ? "#f59e0b" : "#8b5cf6" }}
                        animationDuration={500}
                    />

                    {/* Mode Badge within Chart */}
                    {predictionData?.slow_absorption_active && (
                        <text x="50%" y="30" textAnchor="middle" fill="#f59e0b" fontSize="12" fontWeight="bold" opacity="0.8">
                            🐢 {predictionData.slow_absorption_reason || "Modo Absorción Lenta Activo (>5h)"}
                        </text>
                    )}

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
        const baseItem = payload.find(p => p.dataKey === 'baselinePrediction');

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
                {isPred && baseItem && baseItem.value != null && (
                    <div style={{ fontSize: '0.8rem', color: '#94a3b8', borderTop: '1px solid #f1f5f9', paddingTop: '4px' }}>
                        Sin bolo: <strong>{Math.round(baseItem.value)}</strong>
                    </div>
                )}
            </div>
        );
    }
    return null;
}

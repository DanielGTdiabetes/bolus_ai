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

        const quantileSources = predictionData?.quantiles || predictionData?.percentiles || predictionData?.prediction_quantiles;

        const resolveQuantileValue = (quantileKey, tMin) => {
            const directSeries = predictionData?.[`${quantileKey}_series`];
            const directPoint = directSeries?.find(point => point.t_min === tMin);
            if (directPoint?.bg != null) {
                return directPoint.bg;
            }

            const quantileSeries = quantileSources?.[quantileKey] || quantileSources?.[`${quantileKey}_series`];
            const normalizedSeries = Array.isArray(quantileSeries) ? quantileSeries : quantileSeries?.series;
            const quantilePoint = normalizedSeries?.find(point => point.t_min === tMin);
            return quantilePoint?.bg ?? null;
        };

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

            // [ML Beta] Resolve ML prediction if available
            let mlVal = null;
            if (predictionData.ml_series) {
                const mPoint = predictionData.ml_series.find(m => m.t_min === p.t_min);
                if (mPoint) mlVal = mPoint.bg;
            }

            const p10Val = resolveQuantileValue('p10', p.t_min);
            const p90Val = resolveQuantileValue('p90', p.t_min);
            const aiP50Val = mlVal ?? p.bg;

            return {
                timeLabel: new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
                aiP50: aiP50Val,
                baselinePrediction: bVal,
                p10Prediction: p10Val,
                p90Prediction: p90Val,
                p90BandRange: p10Val != null && p90Val != null ? Math.max(p90Val - p10Val, 0) : null,
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
                aiP50: lastReal.bg, // Start prediction curve at actual BG
                baselinePrediction: lastReal.bg, // Start ghost curve at actual BG
                p10Prediction: lastReal.bg,
                p90Prediction: lastReal.bg,
                p90BandRange: 0,
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

    // Recalculate max/min for domain (Global: History + Prediction)
    const allValues = chartData.flatMap(d => [
        d.bg,
        d.aiP50,
        d.baselinePrediction,
        d.p10Prediction,
        d.p90Prediction
    ]).filter(v => v != null && !isNaN(v));
    const maxVal = allValues.length ? Math.max(...allValues) : 180;
    const minVal = allValues.length ? Math.min(...allValues) : 70;

    // Gradient Thresholds for the AREA (History Only)
    // We must use the Max/Min of the BG data specifically, because the Gradient is applied to the BG Area shape.
    // If we use Global max (e.g. 200 from prediction) but BG max is 112, offset 0.1 applies to 112, making it red!
    const bgValues = chartData.map(d => d.bg).filter(v => v != null && !isNaN(v));
    const maxBg = bgValues.length ? Math.max(...bgValues) : 180;
    const minBg = bgValues.length ? Math.min(...bgValues) : 70;

    const HIGH = 180;
    const LOW = 70;

    // Calculate Gradient based on BG Range (The Area's bounding box)
    const bgRange = maxBg - minBg;
    let offHigh = 0;
    let offLow = 1;

    if (bgRange > 0) {
        if (maxBg > HIGH) offHigh = (maxBg - HIGH) / bgRange;
        if (minBg < LOW) offLow = (maxBg - LOW) / bgRange;
    }
    offHigh = Math.min(Math.max(offHigh, 0), 1);
    offLow = Math.min(Math.max(offLow, 0), 1);

    // Color Logic: Safe if History is within limits
    const isSafe = minBg >= LOW && maxBg <= HIGH;
    const strokeColor = isSafe ? '#3b82f6' : 'url(#splitColor)';
    const fillColor = isSafe ? 'rgba(59, 130, 246, 0.2)' : 'url(#splitFill)';

    const nightPatternApplied = Boolean(predictionData?.prediction_meta?.pattern?.applied);
    const hasQuantileBand = chartData.some(d => d.p90BandRange != null && d.p10Prediction != null);
    const confidenceRaw = predictionData?.quality || predictionData?.absorption_confidence || 'medium';
    const confidenceLabel = confidenceRaw === 'high' ? 'Alta' : (confidenceRaw === 'low' ? 'Baja' : 'Media');
    const confidenceColor = confidenceRaw === 'high' ? '#16a34a' : (confidenceRaw === 'low' ? '#dc2626' : '#f59e0b');

    return (
        <div style={{ width: '100%', height: '100%', minHeight: '160px', marginTop: '0.5rem', position: 'relative' }}>
            <div
                style={{
                    position: 'absolute',
                    top: '4px',
                    left: '8px',
                    background: '#f8fafc',
                    color: '#64748b',
                    fontSize: '0.65rem',
                    fontWeight: 700,
                    padding: '2px 6px',
                    borderRadius: '999px',
                    border: '1px solid #e2e8f0',
                    zIndex: 2
                }}
            >
                Informativo
            </div>
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

                    {/* Uncertainty Band p10–p90 */}
                    {hasQuantileBand && (
                        <>
                            <Area
                                yAxisId="bg"
                                type="monotone"
                                dataKey="p10Prediction"
                                stackId="confidenceBand"
                                stroke="none"
                                fill="transparent"
                                isAnimationActive={false}
                            />
                            <Area
                                yAxisId="bg"
                                type="monotone"
                                dataKey="p90BandRange"
                                stackId="confidenceBand"
                                stroke="none"
                                fill="rgba(129, 140, 248, 0.2)"
                                isAnimationActive={false}
                                name="Banda p10–p90 (info)"
                            />
                        </>
                    )}

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

                    {/* IA p50 Curve */}
                    <Line
                        yAxisId="bg"
                        type="monotone"
                        dataKey="aiP50"
                        stroke={predictionData?.slow_absorption_active ? "#f59e0b" : "#8b5cf6"} // Amber-500 if slow, else Violet-500
                        strokeWidth={3}
                        strokeDasharray={predictionData?.slow_absorption_active ? "0" : "5 5"} // Solid line if slow (more certain/modelled-heavy)
                        dot={false}
                        activeDot={{ r: 4, fill: predictionData?.slow_absorption_active ? "#f59e0b" : "#8b5cf6" }}
                        animationDuration={500}
                        name="IA p50"
                    />

                    {/* Mode Badge within Chart */}
                    {predictionData?.slow_absorption_active && (
                        <text x="50%" y="30" textAnchor="middle" fill="#f59e0b" fontSize="12" fontWeight="bold" opacity="0.8">
                            🐢 {predictionData.slow_absorption_reason || "Modo Absorción Lenta Activo (>5h)"}
                        </text>
                    )}

                </ComposedChart>
            </ResponsiveContainer>
            <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: '8px', marginTop: '0.35rem', fontSize: '0.7rem', color: '#94a3b8' }}>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{ width: '10px', height: '2px', background: '#94a3b8', display: 'inline-block' }}></span>
                        Baseline (informativo)
                    </span>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{ width: '10px', height: '2px', background: '#8b5cf6', display: 'inline-block' }}></span>
                        IA p50 (informativo)
                    </span>
                    {hasQuantileBand && (
                        <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <span style={{ width: '10px', height: '10px', background: 'rgba(129, 140, 248, 0.25)', borderRadius: '2px', display: 'inline-block' }}></span>
                            Banda p10–p90 (informativo)
                        </span>
                    )}
                </div>
                <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: confidenceColor }}></span>
                    Confianza {confidenceLabel} (informativo)
                </span>
            </div>
            <div style={{ marginTop: '0.25rem', fontSize: '0.7rem', color: '#94a3b8' }}>
                No usar para decisiones.
            </div>
        </div>
    );
}

function CustomTooltip({ active, payload, label }) {
    if (active && payload && payload.length) {
        const bgItem = payload.find(p => p.dataKey === 'bg');
        const predItem = payload.find(p => p.dataKey === 'aiP50');
        const baseItem = payload.find(p => p.dataKey === 'baselinePrediction');
        const p10Item = payload.find(p => p.dataKey === 'p10Prediction');
        const p90Item = payload.find(p => p.dataKey === 'p90Prediction');

        // Prioritize actual BG, else show prediction
        const val = bgItem?.value ?? predItem?.value;
        const isPred = !bgItem?.value && predItem?.value;

        return (
            <div style={{ background: 'rgba(255, 255, 255, 0.95)', padding: '10px', borderRadius: '12px', boxShadow: '0 4px 15px rgba(0,0,0,0.1)', border: '1px solid #e2e8f0', minWidth: '120px' }}>
                <p style={{ margin: 0, fontSize: '0.8rem', color: '#64748b', marginBottom: '5px' }}>
                    {label} {isPred && <span style={{ color: '#8b5cf6' }}>(IA p50)</span>}
                </p>

                <div style={{ fontSize: '1.2rem', fontWeight: 800, color: isPred ? '#8b5cf6' : '#1e293b', lineHeight: 1, marginBottom: '8px' }}>
                    {Math.round(val || 0)} <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#94a3b8' }}>mg/dL</span>
                </div>
                {isPred && baseItem && baseItem.value != null && (
                    <div style={{ fontSize: '0.8rem', color: '#94a3b8', borderTop: '1px solid #f1f5f9', paddingTop: '4px' }}>
                        Sin bolo: <strong>{Math.round(baseItem.value)}</strong>
                    </div>
                )}
                {isPred && p10Item?.value != null && p90Item?.value != null && (
                    <div style={{ fontSize: '0.8rem', color: '#818cf8', paddingTop: '2px', fontWeight: 600 }}>
                        Banda p10–p90: <strong>{Math.round(p10Item.value)}–{Math.round(p90Item.value)}</strong>
                    </div>
                )}
            </div>
        );
    }
    return null;
}

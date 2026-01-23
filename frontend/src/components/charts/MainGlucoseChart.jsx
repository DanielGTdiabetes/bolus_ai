import React, { useState, useEffect } from 'react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, ComposedChart, Line } from 'recharts';
import { getGlucoseEntries, getLocalNsConfig } from '../../lib/api';

export function MainGlucoseChart({ isLow, predictionData, chartHeight = 160, hideLegend = false }) {
    // ... (rest of state/effect - no changes needed to logic above return)

    // ... (logic)
    const nightPatternApplied = Boolean(
        predictionData?.night_pattern_applied ??
        predictionData?.nightPatternApplied ??
        false
    );

    // Return JSX
    return (
        <div style={{ width: '100%', marginTop: '0.5rem', position: 'relative', display: 'flex', flexDirection: 'column' }}>
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
                    title="Ajuste basado en tu patrón nocturno (00:00–03:45)."
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
            <div style={{ width: '100%', height: chartHeight, minHeight: chartHeight }}>
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
                                    name="Rango Probable"
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
                                name="Sin acción (Ref)"
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
                            name="Predicción IA"
                        />
                    </ComposedChart>
                </ResponsiveContainer>
            </div>

            {/* LEGEND - Refined Labels & Layout */}
            {!hideLegend && (
                <>
                    <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: '8px', marginTop: '0.75rem', fontSize: '0.7rem', color: '#64748b', paddingBottom: '4px' }}>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
                            <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <span style={{ width: '10px', height: '2px', background: '#94a3b8', display: 'inline-block' }}></span>
                                Sin acción (Ref)
                            </span>
                            <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <span style={{ width: '10px', height: '2px', background: '#8b5cf6', display: 'inline-block' }}></span>
                                Predicción IA
                            </span>
                            {hasQuantileBand && (
                                <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                    <span style={{ width: '10px', height: '10px', background: 'rgba(129, 140, 248, 0.25)', borderRadius: '2px', display: 'inline-block' }}></span>
                                    Rango Probable
                                </span>
                            )}
                        </div>
                        <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: confidenceColor }}></span>
                            Confianza {confidenceLabel}
                        </span>
                    </div>
                    <div style={{ marginTop: '0.25rem', fontSize: '0.65rem', color: '#94a3b8' }}>
                        * No utilizar para decisiones médicas directas.
                    </div>
                </>
            )}
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

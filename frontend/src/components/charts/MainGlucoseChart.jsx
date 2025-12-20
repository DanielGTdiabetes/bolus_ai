import React, { useState, useEffect } from 'react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, ComposedChart, Bar, Line } from 'recharts';
import { getGlucoseEntries, fetchTreatments, getLocalNsConfig } from '../../lib/api';
import { Card } from '../ui/Atoms';

export function MainGlucoseChart({ isLow }) {
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        async function load() {
            setLoading(true);
            try {
                const config = getLocalNsConfig();
                const [glucoseData, treatmentData] = await Promise.all([
                    getGlucoseEntries(36), // 36 * 5 = 180 min = 3h
                    fetchTreatments({ ...config, count: 20 })
                ]);

                // Map Glucose
                // Glucose entry: { date: ms, sgv: number, ... }
                // Reverse to be chronological
                const sortedG = [...glucoseData].reverse();
                if (sortedG.length === 0) {
                    setData([]);
                    return;
                }

                const startTime = sortedG[0].date;
                const endTime = sortedG[sortedG.length - 1].date;

                // Process Treatments to fit into the timeline
                // We map treatment to the closest glucose point (simplification)
                // Or just use timestamp.
                // Treatment: { created_at: string, insulin: number, carbs: number }

                const treatments = treatmentData.map(t => ({
                    time: new Date(t.created_at || t.timestamp).getTime(),
                    insulin: parseFloat(t.insulin) || 0,
                    carbs: parseFloat(t.carbs) || 0,
                    notes: t.notes
                })).filter(t => t.time >= startTime && t.time <= endTime + 1000 * 60 * 10); // slightly wider window

                // Merge Data
                // We create a unified timeline based on glucose points
                // For each glucose point, we check if there's a treatment within +/- 2.5 mins

                const merged = sortedG.map(g => {
                    // Find treatments close to this point
                    const match = treatments.find(t => Math.abs(t.time - g.date) < 2.5 * 60 * 1000); // 2.5 min window

                    return {
                        timeLabel: new Date(g.date).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
                        bg: g.sgv,
                        insulin: match ? match.insulin : 0,
                        carbs: match ? match.carbs : 0,
                        hasTreatment: !!match
                    };
                });

                setData(merged);
            } catch (err) {
                console.error("Chart load error", err);
            } finally {
                setLoading(false);
            }
        }
        load();
    }, []);

    if (loading || !data.length) return null;

    // Dynamic Coloring Logic
    const maxVal = Math.max(...data.map(d => d.bg));
    const minVal = Math.min(...data.map(d => d.bg));
    const range = maxVal - minVal;

    // Calculate offsets (0 is top/max in SVG usually, wait, in Recharts Y axis:
    // If we define gradient x1=0 y1=0 (top) to x2=0 y2=1 (bottom).
    // offset 0% is MAX BG. offset 100% is MIN BG.

    // Thresholds
    const highT = 180;
    const lowT = 70;

    const offHigh = range <= 0 ? 0 : (maxVal - highT) / range;
    const offLow = range <= 0 ? 1 : (maxVal - lowT) / range;

    // Clamp
    const off1 = Math.min(Math.max(offHigh, 0), 1);
    const off2 = Math.min(Math.max(offLow, 0), 1);

    return (
        <div style={{ width: '100%', height: '140px', marginTop: '1rem' }}>
            <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={data} margin={{ top: 5, right: 0, left: -20, bottom: 0 }}>
                    <defs>
                        <linearGradient id="splitColor" x1="0" y1="0" x2="0" y2="1">
                            {/* Top (Max BG) to High Threshold: Red/Orange */}
                            <stop offset={off1} stopColor="#ef4444" stopOpacity={1} />
                            {/* Start Normal Range: Blue */}
                            <stop offset={off1} stopColor="#3b82f6" stopOpacity={1} />
                            {/* End Normal Range */}
                            <stop offset={off2} stopColor="#3b82f6" stopOpacity={1} />
                            {/* Bottom (Low BG): Red */}
                            <stop offset={off2} stopColor="#ef4444" stopOpacity={1} />
                        </linearGradient>
                        <linearGradient id="splitFill" x1="0" y1="0" x2="0" y2="1">
                            <stop offset={off1} stopColor="#ef4444" stopOpacity={0.3} />
                            <stop offset={off1} stopColor="#3b82f6" stopOpacity={0.3} />
                            <stop offset={off2} stopColor="#3b82f6" stopOpacity={0.3} />
                            <stop offset={off2} stopColor="#ef4444" stopOpacity={0.3} />
                        </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                    <XAxis dataKey="timeLabel" tick={{ fontSize: 10, fill: '#94a3b8' }} interval="preserveStartEnd" minTickGap={30} />
                    <YAxis yAxisId="bg" domain={['auto', 'auto']} tick={{ fontSize: 10, fill: '#94a3b8' }} width={30} />
                    <YAxis yAxisId="treat" orientation="right" hide domain={[0, 'auto']} />

                    <Tooltip
                        contentStyle={{ borderRadius: '8px', fontSize: '0.8rem', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                        labelStyle={{ color: '#64748b', marginBottom: '4px' }}
                    />

                    {/* Visual Guides */}
                    <ReferenceLine yAxisId="bg" y={lowT} stroke="red" strokeDasharray="3 3" opacity={0.2} />
                    <ReferenceLine yAxisId="bg" y={highT} stroke="orange" strokeDasharray="3 3" opacity={0.2} />

                    {/* Carbs Bar (Orange) */}
                    <Bar yAxisId="treat" dataKey="carbs" fill="#f97316" barSize={8} radius={[2, 2, 0, 0]} name="Carbs (g)" />

                    {/* Insulin Bar (Blue/Cyan) */}
                    <Bar yAxisId="treat" dataKey="insulin" fill="#06b6d4" barSize={8} radius={[2, 2, 0, 0]} name="Bolus (U)" />

                    {/* Glucose Line */}
                    <Area
                        yAxisId="bg"
                        type="monotone"
                        dataKey="bg"
                        stroke="url(#splitColor)"
                        strokeWidth={3}
                        fill="url(#splitFill)"
                        name="Glucosa"
                    />
                </ComposedChart>
            </ResponsiveContainer>
        </div>
    );
}

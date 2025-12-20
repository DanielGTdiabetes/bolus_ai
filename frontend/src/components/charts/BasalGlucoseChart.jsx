import React, { useState, useEffect } from 'react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import { getGlucoseEntries, getLatestBasal } from '../../lib/api';
import { Card } from '../ui/Atoms';

export function BasalGlucoseChart() {
    const [data, setData] = useState([]);
    const [basalLevel, setBasalLevel] = useState(0);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        async function load() {
            try {
                const [glucoseData, basalData] = await Promise.all([
                    getGlucoseEntries(288), // Last 24h (approx)
                    getLatestBasal()
                ]);

                // Calculate estimated basal rate (U/hr) assuming flat profile
                // This is a simplification for visualization
                const dose = basalData?.dose_u || 0;
                const rate = dose / 24;
                setBasalLevel(rate);

                // Process Glucose Data
                // api returns list of { sgv, dateString, date (ms) ... }
                // We want to reverse it so it's chronological (oldest to newest)
                const sorted = [...glucoseData].reverse().map(item => ({
                    time: new Date(item.date).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
                    bg: item.sgv,
                    timestamp: item.date
                }));

                setData(sorted);
            } catch (err) {
                console.error("Error loading chart data", err);
            } finally {
                setLoading(false);
            }
        }
        load();
    }, []);

    if (loading) return <Card>Cargando gráfica...</Card>;
    if (!data.length) return null;

    return (
        <Card style={{ marginBottom: '1rem', height: '300px', padding: '10px' }}>
            <h3 style={{ margin: '0 0 10px 0', fontSize: '1rem', color: '#64748b' }}>Glucosa 24h vs Basal</h3>
            <div style={{ width: '100%', height: '240px' }}>
                <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={data}>
                        <defs>
                            <linearGradient id="colorBg" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                                <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                            </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                        <XAxis
                            dataKey="time"
                            interval="preserveStartEnd"
                            minTickGap={50}
                            tick={{ fontSize: 10, fill: '#94a3b8' }}
                        />
                        <YAxis
                            domain={[40, 300]}
                            hide={false}
                            tick={{ fontSize: 10, fill: '#94a3b8' }}
                            width={30}
                        />
                        <Tooltip
                            contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                            itemStyle={{ color: '#1e293b', fontWeight: 600 }}
                        />

                        {/* Target Range Area (70-160) - Visual Guide */}
                        <ReferenceLine y={70} stroke="red" strokeDasharray="3 3" opacity={0.5} />
                        <ReferenceLine y={160} stroke="orange" strokeDasharray="3 3" opacity={0.5} />

                        <Area
                            type="monotone"
                            dataKey="bg"
                            stroke="#3b82f6"
                            strokeWidth={2}
                            fillOpacity={1}
                            fill="url(#colorBg)"
                            name="Glucosa"
                            unit=" mg/dL"
                        />
                    </AreaChart>
                </ResponsiveContainer>
            </div>
            <div style={{ textAlign: 'center', fontSize: '0.75rem', color: '#64748b', marginTop: '5px' }}>
                Basal Estimada: <strong>{(basalLevel * 24).toFixed(1)} U/día</strong> (~{basalLevel.toFixed(2)} U/h)
            </div>
        </Card>
    );
}

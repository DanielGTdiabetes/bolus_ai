import React, { useState, useEffect } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { MainGlucoseChart } from '../components/charts/MainGlucoseChart';
import { apiFetch, toJson, getCurrentGlucose, getLocalNsConfig } from '../lib/api';
import { useInterval } from '../hooks/useInterval';
import { getDualPlan, getDualPlanTiming } from '../modules/core/store';

export default function ForecastPage() {
    const [prediction, setPrediction] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [lastUpdated, setLastUpdated] = useState(null);

    const loadForecast = async () => {
        setLoading(true);
        setError(null);
        try {
            const params = new URLSearchParams();

            // Attempt to get current BG to seed the forecast (avoid backend default mismatch)
            try {
                const bgData = await getCurrentGlucose();
                let bgVal = null;
                // Handle different potential return shapes (array or object)
                if (bgData) {
                    if (bgData.bg_mgdl) bgVal = bgData.bg_mgdl; // /api/nightscout/current returns this (stateless/server)
                    else if (bgData.sgv) bgVal = bgData.sgv;    // Raw NS entry or fallback
                    // If array (raw entries)
                    else if (Array.isArray(bgData) && bgData.length > 0) {
                        if (bgData[0].sgv) bgVal = bgData[0].sgv;
                        else if (bgData[0].bg_mgdl) bgVal = bgData[0].bg_mgdl;
                    }
                }

                if (bgVal) params.append("start_bg", String(bgVal));
            } catch (bgErr) {
                console.warn("Could not fetch local BG for forecast seed", bgErr);
            }

            // Inject Dual Bolus Plan if active
            const activePlan = getDualPlan();
            if (activePlan && activePlan.later_u_planned > 0) {
                const timing = getDualPlanTiming(activePlan);
                if (timing && typeof timing.remaining_min === 'number') {
                    params.append("future_insulin_u", activePlan.later_u_planned);
                    params.append("future_insulin_delay_min", Math.max(0, Math.round(timing.remaining_min)));
                    // Pass duration if available
                    if (timing.duration_min) {
                        params.append("future_insulin_duration_min", Math.round(timing.duration_min));
                    }
                }
            }

            const qs = params.toString() ? "?" + params.toString() : "";
            const res = await apiFetch("/api/forecast/current" + qs);
            if (!res.ok) throw new Error("Error cargando predicción");
            const data = await toJson(res);
            setPrediction(data);
            setLastUpdated(new Date());
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadForecast();
    }, []);

    useInterval(loadForecast, 60000);

    return (
        <>
            <Header title="Predicción Detallada" showBack={true} />
            <main className="page" style={{ paddingBottom: '90px' }}>

                <div className="card" style={{ padding: '1rem', marginBottom: '1rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                        <h2 style={{ fontSize: '1.2rem', margin: 0, color: '#1e293b' }}>Simulación a 6 Horas</h2>
                        <button onClick={loadForecast} disabled={loading} style={{ background: 'none', border: 'none', color: loading ? '#94a3b8' : '#3b82f6', cursor: loading ? 'wait' : 'pointer' }}>
                            {loading ? '⏳ Cargando...' : '🔄 Actualizar'}
                        </button>
                    </div>

                    {loading && !prediction && <div className="spinner"></div>}

                    {error && (
                        <div style={{ padding: '1rem', background: '#fee2e2', color: '#991b1b', borderRadius: '8px', marginBottom: '1rem' }}>
                            ⚠️ {error}
                        </div>
                    )}

                    {prediction && (
                        <div className="fade-in">
                            {/* Big Chart */}
                            <div style={{ width: '100%', marginBottom: '1rem' }}>
                                <MainGlucoseChart predictionData={prediction} chartHeight={300} />
                            </div>

                            {/* Summary Stats */}
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1rem' }}>
                                <StatTile label="Mínimo Estimado" value={prediction.summary.min_bg} unit="mg/dL" color={prediction.summary.min_bg < 70 ? '#ef4444' : '#3b82f6'} />
                                <StatTile label="Máximo Estimado" value={prediction.summary.max_bg} unit="mg/dL" color={prediction.summary.max_bg > 180 ? '#f59e0b' : '#3b82f6'} />
                                <StatTile label="Glucosa Final (6h)" value={prediction.summary.ending_bg} unit="mg/dL" />
                                <StatTile label="Tiempo al Mínimo" value={prediction.summary.time_to_min ? `en ${prediction.summary.time_to_min} min` : '--'} />
                            </div>

                            <div style={{ marginTop: '1rem', fontSize: '0.8rem', color: '#94a3b8', textAlign: 'center' }}>
                                Última actualización: {lastUpdated ? lastUpdated.toLocaleTimeString() : '--'}
                            </div>
                        </div>
                    )}
                </div>

            </main>
            <BottomNav activeTab="home" />
        </>
    );
}

function StatTile({ label, value, unit, color = '#334155' }) {
    return (
        <div style={{ background: '#f8fafc', padding: '0.8rem', borderRadius: '12px', border: '1px solid #e2e8f0', textAlign: 'center' }}>
            <div style={{ fontSize: '0.75rem', color: '#64748b', marginBottom: '4px' }}>{label}</div>
            <div style={{ fontSize: '1.2rem', fontWeight: 700, color: color }}>
                {value ?? '--'} <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>{unit}</span>
            </div>
        </div>
    );
}

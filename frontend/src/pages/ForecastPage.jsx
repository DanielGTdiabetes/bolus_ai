import React, { useState, useEffect } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { MainGlucoseChart } from '../components/charts/MainGlucoseChart';
import { apiFetch, toJson, getCurrentGlucose, getLocalNsConfig } from '../lib/api';
import { useInterval } from '../hooks/useInterval';

export default function ForecastPage() {
    const [prediction, setPrediction] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [lastUpdated, setLastUpdated] = useState(null);

    const loadForecast = async () => {
        setLoading(true);
        setError(null);
        try {
            // Attempt to get current BG to seed the forecast (avoid backend default mismatch)
            let query = "";
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

                if (bgVal) query = `?start_bg=${bgVal}`;
            } catch (bgErr) {
                console.warn("Could not fetch local BG for forecast seed", bgErr);
            }

            const res = await apiFetch("/api/forecast/current" + query);
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
                            <div style={{ height: '300px', width: '100%', marginBottom: '1rem' }}>
                                <MainGlucoseChart predictionData={prediction} />
                            </div>

                            {/* Summary Stats */}
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1rem' }}>
                                <StatTile label="Mínimo Estimado" value={prediction.summary.min_bg} unit="mg/dL" color={prediction.summary.min_bg < 70 ? '#ef4444' : '#3b82f6'} />
                                <StatTile label="Máximo Estimado" value={prediction.summary.max_bg} unit="mg/dL" color={prediction.summary.max_bg > 180 ? '#f59e0b' : '#3b82f6'} />
                                <StatTile label="Glucosa Final (6h)" value={prediction.summary.ending_bg} unit="mg/dL" />
                                <StatTile label="Tiempo al Mínimo" value={prediction.summary.time_to_min ? `en ${prediction.summary.time_to_min} min` : '--'} />
                            </div>

                            {/* Warnings */}
                            {prediction.warnings && prediction.warnings.length > 0 && (
                                <div style={{ background: '#fff7ed', border: '1px solid #fdba74', padding: '1rem', borderRadius: '8px' }}>
                                    <h4 style={{ margin: '0 0 0.5rem 0', color: '#c2410c', fontSize: '0.9rem' }}>Advertencias del Modelo</h4>
                                    <ul style={{ margin: 0, paddingLeft: '1.2rem', color: '#ea580c', fontSize: '0.85rem' }}>
                                        {prediction.warnings.map((w, i) => <li key={i}>{w}</li>)}
                                    </ul>
                                </div>
                            )}

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

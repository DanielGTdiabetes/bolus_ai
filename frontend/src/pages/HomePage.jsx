import React, { useState, useEffect } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { Card, Button } from '../components/ui/Atoms';
import { useInterval } from '../hooks/useInterval';
import {
    getCurrentGlucose, getIOBData, fetchTreatments, getLocalNsConfig, getGlucoseEntries, apiFetch, toJson
} from '../lib/api';
import { formatTrend } from '../modules/core/utils';
import { navigate } from '../modules/core/router';
import { useStore } from '../hooks/useStore';
import { getDualPlan, getDualPlanTiming } from '../modules/core/store';
import { RESTAURANT_MODE_ENABLED } from '../lib/featureFlags';

import { MainGlucoseChart } from '../components/charts/MainGlucoseChart';

function GlucoseHero({ onRefresh }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [prediction, setPrediction] = useState(null);

    // Auto-refresh config (hook requires interval in ms or null)
    useInterval(() => load(), 60000);

    const load = async () => {
        setLoading(true);
        try {
            const config = getLocalNsConfig();
            // Fetch only current for the big number
            const current = await getCurrentGlucose(config);
            setData(current);

            // Ambient Forecast (try catch to not block main UI)
            try {
                const predRes = await apiFetch("/api/forecast/current");
                if (predRes.ok) {
                    const predData = await toJson(predRes);
                    setPrediction(predData);
                }
            } catch (err) {
                console.warn("Forecast fetch error", err);
            }

        } catch (e) {
            console.warn("BG Fetch Error", e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { load(); }, [onRefresh]);

    const displayVal = data ? Math.round(data.bg_mgdl) : '--';
    const displayArrow = data ? (data.trendArrow || formatTrend(data.trend, false)) : '--';
    const displayTime = data ? `${Math.round(data.age_minutes)} min` : '--';

    const isLow = data ? data.bg_mgdl <= 70 : false;
    const arrowColor = data ? (data.bg_mgdl > 180 ? '#ef4444' : (isLow ? '#991b1b' : '#10b981')) : '#64748b';
    const bgColor = isLow ? '#fef2f2' : '#fff';
    const borderColor = isLow ? '#ef4444' : '#fff';
    const boxShadow = isLow ? '0 0 0 2px #fecaca' : '0 4px 6px -1px rgba(0, 0, 0, 0.05)';

    // Check for prediction alerts
    useEffect(() => {
        if (prediction && prediction.summary) {
            const min = prediction.summary.min_bg;
            const max = prediction.summary.max_bg;
            let warn = false;
            // Warn if predicted low < 70 or high > 250
            if (min < 70 || max > 250) {
                warn = true;
            }
            localStorage.setItem('forecast_warning', warn ? 'true' : 'false');
            // Trigger update in Header
            window.dispatchEvent(new Event('forecast-update'));
        }
    }, [prediction]);

    return (
        <section className="card glucose-hero" style={{
            marginBottom: '1rem', padding: '1.5rem', borderRadius: '16px',
            background: bgColor, border: isLow ? `1px solid ${borderColor}` : 'none',
            boxShadow: boxShadow, transition: 'all 0.3s ease', cursor: 'pointer'
        }} onClick={() => navigate('#/forecast')}>
            <div className="gh-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                <div style={{ fontSize: '0.9rem', fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Glucosa Actual</div>
                <button onClick={(e) => { e.stopPropagation(); load(); }} style={{ background: 'none', border: 'none', fontSize: '1.2rem', cursor: 'pointer', color: loading ? '#cbd5e1' : '#3b82f6' }}>
                    {loading ? '...' : '↻'}
                </button>
            </div>

            {/* Visual Warning for Compression */}
            {data && data.is_compression && (
                <div style={{ background: '#fef2f2', color: '#991b1b', fontSize: '0.8rem', padding: '0.4rem', borderRadius: '6px', marginBottom: '0.5rem', border: '1px solid #fca5a5', display: 'flex', alignItems: 'center', gap: '5px' }}>
                    <span>⚠️</span>
                    <span title={data.compression_reason}>Posible falsa bajada (Compresión)</span>
                </div>
            )}

            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'center', gap: '0.5rem' }}>
                <span style={{ fontSize: '3.5rem', fontWeight: 800, color: arrowColor, lineHeight: 1, textDecoration: data?.is_compression ? 'underline 3px dotted #fca5a5' : 'none' }}>{displayVal}</span>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
                    <span style={{ fontSize: '1.5rem', color: arrowColor, fontWeight: 800 }}>{displayArrow}</span>
                    <span style={{ fontSize: '0.8rem', color: '#94a3b8', fontWeight: 600 }}>mg/dL</span>
                </div>
            </div>
            <div style={{ textAlign: 'center', marginTop: '0.5rem' }}>
                <span style={{ background: '#f1f5f9', color: '#64748b', fontSize: '0.75rem', padding: '4px 8px', borderRadius: '12px', fontWeight: 600 }}>
                    Hace {displayTime}
                </span>
            </div>

            {/* Advanced Graph with Ambient Prediction */}
            <MainGlucoseChart isLow={isLow} predictionData={prediction} />

            {/* Prediction Alerts */}
            {prediction && prediction.summary && (prediction.summary.min_bg < 70 || prediction.summary.max_bg > 250) && (
                <div style={{ marginTop: '0.8rem', padding: '0.5rem', background: prediction.summary.min_bg < 70 ? '#fef2f2' : '#fffbeb', border: `1px solid ${prediction.summary.min_bg < 70 ? '#fecaca' : '#fcd34d'}`, borderRadius: '8px', display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.8rem', color: '#1e293b' }}>
                    <span style={{ fontSize: '1.2rem' }}>{prediction.summary.min_bg < 70 ? '📉' : '📈'}</span>
                    <div>
                        <strong>{prediction.summary.min_bg < 70 ? 'Riesgo de Hipoglucemia' : 'Tendencia Alta'}</strong>
                        <div style={{ fontSize: '0.75rem', color: '#64748b' }}>
                            {prediction.summary.min_bg < 70 ? `Mínimo estimado: ${prediction.summary.min_bg} mg/dL` : `Máximo estimado: ${prediction.summary.max_bg} mg/dL`}
                        </div>
                    </div>
                </div>
            )}

            <div style={{ textAlign: 'center', marginTop: '0.5rem', fontSize: '0.75rem', color: '#94a3b8' }}>
                Toca para ver predicción detallada
            </div>
        </section>
    );
}

function MetricsGrid({ onRefresh }) {
    const [iob, setIob] = useState({ val: null, status: 'ok', cob: null });
    const [lastBolus, setLastBolus] = useState(null);

    useInterval(() => load(), 60000);

    const load = async () => {
        try {
            const config = getLocalNsConfig();

            // 1. IOB
            const iobData = await getIOBData(config);
            const val = iobData.iob_u ?? iobData.iob_total ?? 0;
            const cob = iobData.cob_total ?? 0;
            const status = iobData.iob_info?.status || 'ok';
            setIob({ val, status, cob });

            // 2. Last Bolus
            const treats = await fetchTreatments({ ...config, count: 20 });
            const last = treats.find(t => parseFloat(t.insulin) > 0 && t.eventType !== 'Temp Basal');
            setLastBolus(last ? parseFloat(last.insulin) : null);

        } catch (e) { console.warn("Metrics Error", e); }
    };

    useEffect(() => { load(); }, [onRefresh]);

    return (
        <div className="metrics-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.75rem', marginBottom: '1.5rem' }}>
            <MetricTile icon="💧" label="IOB" value={iob.val !== null ? iob.val.toFixed(2) : '--'} unit="U" highlight={iob.val > 0} />
            <MetricTile icon="🍪" label="COB" value={iob.cob !== null ? Math.round(iob.cob) : '--'} unit="g" highlight={iob.cob > 0} />
            <MetricTile icon="💉" label="Último" value={lastBolus !== null ? lastBolus : '--'} unit="U" />
        </div>
    );
}

function MetricTile({ icon, label, value, unit, highlight }) {
    return (
        <div style={{ background: highlight ? '#eff6ff' : '#fff', borderRadius: '12px', padding: '1rem 0.5rem', textAlign: 'center', boxShadow: '0 1px 3px rgba(0,0,0,0.05)', border: highlight ? '1px solid #bfdbfe' : '1px solid #f1f5f9' }}>
            <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#64748b', marginBottom: '0.25rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}>
                <span>{icon}</span> {label}
            </div>
            <div style={{ fontSize: '1.1rem', fontWeight: 800, color: highlight ? '#2563eb' : '#334155' }}>
                {value} <span style={{ fontSize: '0.7rem', color: '#94a3b8', fontWeight: 600 }}>{unit}</span>
            </div>
        </div>
    );
}

function QuickActions() {
    // We recreate the QA buttons. 
    // Legacy home uses navigate()
    return (
        <div style={{ marginBottom: '1.5rem' }}>
            <h3 className="section-title" style={{ marginBottom: '1rem', marginTop: 0, fontSize: '1.1rem', color: '#1e293b' }}>Acciones Rápidas</h3>
            <div className="qa-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.5rem' }}>
                <QAButton icon="⭐" label="Favoritos" onClick={() => navigate('#/favorites')} color="#f59e0b" bg="#fffbeb" />
                <QAButton icon="🧮" label="Calcular" onClick={() => navigate('#/bolus')} color="#3b82f6" bg="#eff6ff" />
                <QAButton icon="⚖️" label="Báscula" onClick={() => navigate('#/scale')} color="#10b981" bg="#ecfdf5" />
                <QAButton icon="🍴" label="Alimentos" onClick={() => navigate('#/food-db')} color="#f97316" bg="#fff7ed" />
            </div>
        </div>
    );
}

function QAButton({ icon, label, onClick, color, bg }) {
    return (
        <button className="qa-btn" onClick={onClick} style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            background: '#fff', border: 'none', borderRadius: '12px', padding: '0.8rem 0.2rem', gap: '0.5rem',
            cursor: 'pointer', boxShadow: '0 1px 2px rgba(0,0,0,0.05)', transition: 'transform 0.1s'
        }}>
            <div style={{
                fontSize: '1.4rem', background: bg, width: '42px', height: '42px',
                borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: color
            }}>
                {icon}
            </div>
            <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#475569' }}>{label}</span>
        </button>
    );
}

function ActivityList({ onRefresh }) {
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(false);

    const load = async () => {
        setLoading(true);
        try {
            const config = getLocalNsConfig();

            // Parallel fetch: Treatments + Latest Basal
            const [allTreatments, latestBasal] = await Promise.all([
                fetchTreatments({ ...config, count: 20 }),
                import('../lib/api').then(m => m.getLatestBasal()).catch(() => null)
            ]);

            // Map Treatments
            let combined = allTreatments.map(t => ({
                ...t,
                dateObj: new Date(t.created_at || t.timestamp || t.date),
                type: 'treatment'
            }));

            // Map Basal (if recent, e.g. last 48h)
            if (latestBasal && latestBasal.dose_u > 0 && latestBasal.created_at) {
                const basalDate = new Date(latestBasal.created_at);
                const now = new Date();
                const diffHours = (now - basalDate) / (1000 * 60 * 60);

                if (diffHours < 48) {
                    // Deduplication: Check if already in Nightscout list
                    const isDuplicate = combined.some(t => {
                        const tTime = t.dateObj.getTime();
                        const bTime = basalDate.getTime();
                        const timeDiffMin = Math.abs(tTime - bTime) / 60000;
                        const sameDose = Math.abs((parseFloat(t.insulin) || 0) - latestBasal.dose_u) < 0.1;
                        // If same dose and within 15 min, assume duplicate
                        return sameDose && timeDiffMin < 15;
                    });

                    if (!isDuplicate) {
                        combined.push({
                            insulin: latestBasal.dose_u,
                            carbs: 0,
                            created_at: latestBasal.created_at,
                            dateObj: basalDate,
                            notes: 'Basal Manual',
                            enteredBy: 'BolusAI',
                            type: 'basal'
                        });
                    }
                }
            }

            // Sort DESC
            combined.sort((a, b) => b.dateObj - a.dateObj);

            // Filter valid & Slice
            const valid = combined.filter(t => (parseFloat(t.insulin) > 0 || parseFloat(t.carbs) > 0)).slice(0, 3);
            setItems(valid);
        } catch (e) {
            console.warn(e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { load(); }, [onRefresh]);

    return (
        <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <h3 style={{ margin: 0, fontSize: '1.1rem', color: '#1e293b' }}>Actividad Reciente</h3>
                <span onClick={() => navigate('#/history')} style={{ fontSize: '0.85rem', color: '#3b82f6', fontWeight: 600, cursor: 'pointer' }}>Ver todo</span>
            </div>

            <div className="activity-list" style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', minHeight: '60px' }}>
                {loading && <div className="spinner small"></div>}
                {!loading && items.length === 0 && <div className="text-muted text-center" style={{ fontSize: '0.85rem' }}>Sin actividad reciente</div>}

                {items.map((t, idx) => {
                    const u = parseFloat(t.insulin) || 0;
                    const c = parseFloat(t.carbs) || 0;
                    const isBolus = u > 0;
                    const date = new Date(t.created_at || t.timestamp || t.date);

                    return (
                        <div key={idx} className="activity-item" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', background: '#fff', padding: '0.75rem', borderRadius: '12px', border: '1px solid #f8fafc' }}>
                            <div style={{ fontSize: '1.2rem', background: isBolus ? '#eff6ff' : '#fff7ed', width: '36px', height: '36px', borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                {isBolus ? '💉' : '🍪'}
                            </div>
                            <div style={{ flex: 1 }}>
                                <div style={{ fontWeight: 700, fontSize: '0.9rem', color: '#334155' }}>
                                    {u > 0 && `${u} U `} {c > 0 && `${c} g`}
                                </div>
                                <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>{t.notes || t.enteredBy || 'Entrada'}</div>
                            </div>
                            <div style={{ fontSize: '0.75rem', color: '#cbd5e1', fontWeight: 500 }}>
                                {date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

// ... (previous code)

function RestaurantActivePanel() {
    const [session, setSession] = useState(null);

    const checkSession = () => {
        try {
            const raw = localStorage.getItem('restaurant_session_v1');
            if (!raw) {
                setSession(null);
                return;
            }
            const parsed = JSON.parse(raw);
            // Consider active if initiated (expectedCarbs) and NOT finalized
            const isActive = parsed.expectedCarbs && !parsed.finalizedAt;
            // Also check TTL to avoid showing ancient sessions
            const age = Date.now() - new Date(parsed.createdAt).getTime();
            const TTL = 6 * 60 * 60 * 1000;

            if (isActive && age < TTL) {
                setSession(parsed);
            } else {
                setSession(null);
            }
        } catch {
            setSession(null);
        }
    };

    useInterval(checkSession, 5000); // Check every 5s
    useEffect(checkSession, []);

    if (!session) return null;

    const actualCarbs = session.plates?.reduce((s, p) => s + (p.carbs || 0), 0) || 0;

    return (
        <section className="card active-session-card" style={{ marginBottom: '1rem', background: '#fdf4ff', borderColor: '#f0abfc', border: '1px solid #e879f9', borderRadius: '12px', padding: '1rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                    <h3 style={{ margin: 0, color: '#a21caf', fontSize: '1rem' }}>🍽️ Restaurante Activo</h3>
                    <div style={{ fontSize: '0.8rem', color: '#86198f', marginTop: '4px' }}>
                        Planificado: <strong>{session.expectedCarbs}g</strong> • Llevas: <strong>{actualCarbs}g</strong>
                    </div>
                </div>
                <Button onClick={() => navigate('#/restaurant')} size="sm" style={{ background: '#c026d3', color: '#fff', border: 'none' }}>
                    Continuar
                </Button>
            </div>
        </section>
    );
}

// U2 Dual Panel Component
function DualBolusPanel({ onHide, onCancel }) {
    const [plan, setPlan] = useState(null);
    const [timing, setTiming] = useState(null);
    const [recalcResult, setRecalcResult] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [extraCarbs, setExtraCarbs] = useState(0);

    useInterval(() => {
        const p = getDualPlan();
        if (p) {
            setPlan(p);
            setTiming(getDualPlanTiming(p));
        } else {
            setPlan(null);
        }
    }, 1000); // Check every 1s for better timer resolution

    if (!plan) return null;

    // Use cancel prop or default
    const handleCancelClick = () => {
        if (confirm("¿Cancelar el bolo extendido y borrar datos?")) {
            localStorage.removeItem("bolusai_active_dual_plan");
            setPlan(null);
            if (onCancel) onCancel();
        }
    };

    const handleHideClick = () => {
        if (onHide) onHide();
    };

    const handleRecalc = async () => {
        setLoading(true);
        setError(null);
        setRecalcResult(null);

        try {
            // Dynamic import to avoid circular dependencies with store/api if strictly coupled
            const { recalcSecondBolus, getLocalNsConfig } = await import('../lib/api');
            const { getCalcParams, getDefaultMealParams } = await import('../modules/core/store');

            const nsConfig = getLocalNsConfig();
            if (!nsConfig?.url) throw new Error("Configura Nightscout");

            const calcParams = getCalcParams();
            const slot = plan.slot || "lunch";
            const mealParams = calcParams ? (calcParams[slot] || getDefaultMealParams(calcParams)) : null;

            if (!mealParams) throw new Error("Faltan parámetros de cálculo");

            // Payload logic same as home.js
            const payload = {
                later_u_planned: plan.later_u_planned,
                carbs_additional_g: parseFloat(extraCarbs) || 0,
                params: {
                    cr_g_per_u: mealParams.icr,
                    isf_mgdl_per_u: mealParams.isf,
                    target_bg_mgdl: mealParams.target,
                    round_step_u: calcParams.round_step_u || 0.05,
                    max_bolus_u: calcParams.max_bolus_u || 10,
                    stale_bg_minutes: 15
                },
                nightscout: { url: nsConfig.url, token: nsConfig.token, units: "mgdl" }
            };

            const res = await recalcSecondBolus(payload);
            setRecalcResult(res);

        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    };

    const remaining = (timing?.remaining_min !== undefined && !isNaN(timing.remaining_min)) ? timing.remaining_min : '--';
    const elapsed = (timing?.elapsed_min !== undefined && !isNaN(timing.elapsed_min)) ? timing.elapsed_min : '--';

    return (
        <section className="card u2-card" style={{ marginBottom: '1rem', background: '#f0f9ff', borderColor: '#bae6fd' }}>
            <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h3 style={{ margin: 0, color: '#0369a1', fontSize: '1rem' }}>⏱️ Bolo Dividido</h3>
                <div style={{ display: 'flex', gap: '8px' }}>
                    <button onClick={handleCancelClick} style={{ background: 'none', border: 'none', color: '#ef4444', cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600 }}>Cancelar</button>
                    <button onClick={handleHideClick} style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: '0.8rem' }}>Ocultar</button>
                </div>
            </div>
            <div className="stack" style={{ marginTop: '0.5rem' }}>
                <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: '2rem', fontWeight: 800, color: '#0ea5e9' }}>{remaining} min</div>
                    <div style={{ fontSize: '0.8rem', color: '#64748b' }}>para la segunda dosis</div>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-around', background: '#fff', padding: '0.5rem', borderRadius: '8px' }}>
                    <div style={{ textAlign: 'center' }}>
                        <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>Planificado</div>
                        <strong style={{ color: '#0284c7' }}>{plan.later_u_planned} U</strong>
                    </div>
                    <div style={{ textAlign: 'center' }}>
                        <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>Transcurrido</div>
                        <strong>{elapsed} min</strong>
                    </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <div style={{ flex: 1 }}>
                        <label style={{ fontSize: '0.75rem', fontWeight: 600, color: '#475569' }}>Carbs Extra (g)</label>
                        <input type="number" style={{ width: '100%', padding: '0.6rem', borderRadius: '8px', border: '1px solid #cbd5e1', fontSize: '1.1rem' }}
                            value={extraCarbs} onChange={e => setExtraCarbs(e.target.value)} />
                    </div>
                    <Button onClick={handleRecalc} style={{ marginTop: '1.2rem' }} disabled={loading}>
                        {loading ? '...' : 'Recalcular'}
                    </Button>
                </div>

                {error && <div className="text-danger text-sm">{error}</div>}

                {recalcResult && (
                    <div style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', padding: '0.8rem', borderRadius: '8px', marginTop: '0.5rem' }}>
                        <div style={{ fontSize: '1.5rem', fontWeight: 800, textAlign: 'center', color: '#16a34a', marginBottom: '0.5rem' }}>
                            {recalcResult.u2_recommended_u} U
                        </div>
                        <div className="text-sm">BG: {Math.round(recalcResult.bg_now_mgdl)} | IOB: {recalcResult.iob_now_u?.toFixed(2)}</div>
                        {recalcResult.warnings?.map((w, i) => <div key={i} className="text-xs text-orange-600">⚠️ {w}</div>)}
                    </div>
                )}
            </div>
        </section>
    );
}

export default function HomePage() {
    const [refreshSignal, setRefreshSignal] = useState(0);
    const triggerRefresh = () => setRefreshSignal(prev => prev + 1);

    // Dual Bolus Logic Lifted
    const [activePlan, setActivePlan] = useState(getDualPlan());
    const [dualHidden, setDualHidden] = useState(activePlan ? false : true);

    // Check plan existence periodically
    useInterval(() => {
        const p = getDualPlan();
        if (p && !activePlan) {
            setActivePlan(p);
            setDualHidden(false); // Auto-show on new plan
        } else if (!p && activePlan) {
            setActivePlan(null);
            setDualHidden(true); // Reset
        }
    }, 2000);

    const handleNotificationClick = () => {
        if (activePlan && dualHidden) {
            setDualHidden(false);
            alert("Bolo Dividido visible de nuevo.");
        } else {
            // Standard notification drawer logic if we had one
        }
    };

    return (
        <>
            <Header
                title="Bolus AI"
                showBack={false}
                notificationActive={!!activePlan && dualHidden}
                onNotificationClick={handleNotificationClick}
            />
            <main className="page" style={{ paddingBottom: '90px' }}>
                <GlucoseHero onRefresh={refreshSignal} />
                <RestaurantActivePanel />
                {activePlan && !dualHidden && (
                    <DualBolusPanel
                        onHide={() => setDualHidden(true)}
                        onCancel={() => {
                            setActivePlan(null);
                            setDualHidden(true);
                        }}
                    />
                )}
                <MetricsGrid onRefresh={refreshSignal} />
                <QuickActions />
                <ActivityList onRefresh={refreshSignal} />
            </main>
            <BottomNav activeTab="home" />
        </>
    );
}

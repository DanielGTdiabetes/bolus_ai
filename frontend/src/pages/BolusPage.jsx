import React, { useState, useEffect } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { Card, Button, Input } from '../components/ui/Atoms';
import {
    getCalcParams, getSplitSettings, state
} from '../modules/core/store';
import { formatTrend } from '../modules/core/utils';
import {
    getCurrentGlucose, calculateBolusWithOptionalSplit,
    saveTreatment, getLocalNsConfig, getIOBData
} from '../lib/api';
import { startRestaurantSession } from '../lib/restaurantApi';
import { navigate } from '../modules/core/router';
import { useStore } from '../hooks/useStore';

export default function BolusPage() {
    // State
    const [glucose, setGlucose] = useState('');
    const [carbs, setCarbs] = useState('');
    const [date, setDate] = useState(() => {
        const now = new Date();
        return new Date(now.getTime() - (now.getTimezoneOffset() * 60000)).toISOString().slice(0, 16);
    });
    const [slot, setSlot] = useState('lunch');
    const [correctionOnly, setCorrectionOnly] = useState(false);
    const [dualEnabled, setDualEnabled] = useState(false);

    // Result State
    const [result, setResult] = useState(null); // The raw API response
    const [loading, setLoading] = useState(false);
    const [calculating, setCalculating] = useState(false);
    const [saving, setSaving] = useState(false);

    // Data States
    const [iob, setIob] = useState(null);
    const [nsConfig] = useState(getLocalNsConfig() || {});

    // Memory Ref for Learning (Fat, Protein, Items)
    const mealMetaRef = React.useRef(null);
    const [learningHint, setLearningHint] = useState(null);

    // Effect: Load temp carbs (e.g. from favorites / scale)
    useEffect(() => {
        // We use a small timeout to ensure ensure legacy state is ready or passed via props
        // But since we are inside the same window context, we can read global 'state'
        if (state.tempCarbs) {
            setCarbs(String(state.tempCarbs));
            state.tempCarbs = null; // Clear it
        }

        // Capture Learning Hint
        if (state.tempLearningHint) {
            setLearningHint(state.tempLearningHint);
            // Auto-enable removed: user must confirm.
            // if (state.tempLearningHint.suggest_extended) {
            //     setDualEnabled(true);
            // }
            state.tempLearningHint = null;
        }

        // Capture Meal Meta for Learning
        if (state.tempItems || state.tempFat || state.tempProtein) {
            mealMetaRef.current = {
                items: state.tempItems || [],
                fat: state.tempFat || 0,
                protein: state.tempProtein || 0
            };
        }

        // Auto-enable Dual if fat/protein high (UI Heuristic)
        // Removed auto-set to allow user choice based on suggestion
        // if (state.tempFat > 15 || state.tempProtein > 20) {
        //     setDualEnabled(true);
        // }

        state.tempFat = null;
        state.tempProtein = null;
        state.tempItems = null;

        // Auto-fetch Glucose and IOB
        loadData();
    }, []);

    const loadData = async () => {
        try {
            // Glucose
            const bgData = await getCurrentGlucose(nsConfig);
            if (bgData && bgData.bg_mgdl) {
                setGlucose(String(Math.round(bgData.bg_mgdl)));
            }

            // IOB
            const iobData = await getIOBData(nsConfig);
            if (iobData) {
                const val = iobData.iob_u ?? iobData.iob_total ?? 0;
                setIob(val);
            }
        } catch (e) { console.warn(e); }
    };

    const toggleDual = () => setDualEnabled(!dualEnabled);

    const handleCalculate = async () => {
        setCalculating(true);
        setResult(null);
        try {
            const bgVal = glucose === "" ? NaN : parseFloat(glucose);
            const carbsVal = parseFloat(carbs) || 0;

            if (correctionOnly && isNaN(bgVal)) {
                throw new Error("Para corrección se requiere glucosa.");
            }

            const mealParams = getCalcParams();
            if (!mealParams) throw new Error("No hay configuración de ratios.");

            const slotParams = mealParams[slot];
            if (!slotParams?.icr || !slotParams?.isf || !slotParams?.target) {
                throw new Error(`Faltan datos para el horario '${slot}'.`);
            }

            const payload = {
                carbs_g: correctionOnly ? 0 : carbsVal,
                bg_mgdl: isNaN(bgVal) ? null : bgVal,
                meal_slot: slot,
                target_mgdl: slotParams.target,
                cr_g_per_u: slotParams.icr,
                isf_mgdl_per_u: slotParams.isf,
                dia_hours: mealParams.dia_hours || 4.0,
                round_step_u: mealParams.round_step_u || 0.5,
                max_bolus_u: mealParams.max_bolus_u || 15,
            };

            let splitSettings = getSplitSettings() || {};
            if (dualEnabled) splitSettings.enabled = true;
            else splitSettings.enabled = false;

            const useSplit = (dualEnabled && !correctionOnly && carbsVal > 0);
            const res = await calculateBolusWithOptionalSplit(payload, useSplit ? splitSettings : null);

            setResult(res);
        } catch (e) {
            alert("Error: " + e.message);
        } finally {
            setCalculating(false);
        }
    };

    const handleSave = async (confirmedDose) => {
        setSaving(true);
        try {
            const finalInsulin = parseFloat(confirmedDose);
            if (isNaN(finalInsulin) || finalInsulin < 0) throw new Error("Dosis inválida");

            const customDate = new Date(date);

            const treatment = {
                eventType: "Meal Bolus",
                created_at: customDate.toISOString(),
                carbs: parseFloat(carbs) || 0,
                insulin: finalInsulin,
                enteredBy: state.user?.username || "BolusAI",
                notes: `BolusAI: ${result.kind === 'dual' ? 'Dual' : 'Normal'}. Gr: ${carbs}. BG: ${glucose}`,
                nightscout: {
                    url: nsConfig.url || null,
                }
            };

            // Add Meal Meta for Learning
            if (mealMetaRef.current) {
                // If dual, we capture strategy
                const strategy = result.kind === 'dual' ? {
                    kind: 'dual',
                    total: result.total_u_final,
                    upfront: result.upfront_u,
                    later: result.later_u,
                    delay: result.duration_min
                } : { kind: 'normal', total: result.total_u_final };

                treatment.meal_meta = {
                    ...mealMetaRef.current,
                    strategy
                };
            }

            if (result.kind === 'dual') {
                treatment.notes += ` (Split: ${result.upfront_u} now + ${result.later_u} over ${result.duration_min}m)`;
                // Update global state for HomePage tracking
                state.lastBolusPlan = result.plan;
                state.lastBolusPlan.created_at_ts = Date.now(); // Fix NaN issue
                // If the user modified the immediate dose, we update the 'now' part of the plan
                state.lastBolusPlan.now_u = finalInsulin;
                import('../modules/core/store').then(({ saveDualPlan }) => saveDualPlan(state.lastBolusPlan));
            }

            const apiRes = await saveTreatment(treatment);

            // SPECIAL: Start Restaurant Session if flagged
            // SPECIAL: Start Restaurant Session if flagged
            if (state.tempRestaurantSession) {
                const newSessionPayload = {
                    expectedCarbs: state.tempRestaurantSession.expectedCarbs,
                    expectedFat: state.tempRestaurantSession.expectedFat,
                    expectedProtein: state.tempRestaurantSession.expectedProtein,
                    items: state.tempRestaurantSession.expectedItems || [],
                    notes: "Iniciada desde BolusPage"
                };

                let backendSessionId = null;
                try {
                    const resStart = await startRestaurantSession(newSessionPayload);
                    if (resStart && resStart.sessionId) {
                        backendSessionId = resStart.sessionId;
                    }
                } catch (err) {
                    console.warn("Fallo iniciando sesión backend, usando local:", err);
                }

                const session = {
                    sessionId: backendSessionId || (crypto.randomUUID ? crypto.randomUUID() : String(Date.now())),
                    createdAt: new Date().toISOString(),
                    plates: [],
                    menuWarnings: [],
                    ...state.tempRestaurantSession,
                    actualCarbsTotal: 0,
                    actualFatTotal: 0,
                    actualProteinTotal: 0
                };
                delete session.rawMenuResult;

                localStorage.setItem('restaurant_session_v1', JSON.stringify(session));
                state.tempRestaurantSession = null;

                alert("✅ Bolo guardado. Iniciando sesión de restaurante...");
                navigate('#/restaurant');
                return;
            }

            let msg = "Bolo registrado con éxito (Local).";
            if (apiRes && apiRes.nightscout) {
                if (apiRes.nightscout.uploaded) {
                    msg = "✅ Bolo guardado (Local + Nightscout).";
                } else {
                    msg = "⚠️ Guardado SOLO local.\nError Nightscout: " + (apiRes.nightscout.error || "Desconocido");
                }
            }
            alert(msg);
            navigate('#/');

        } catch (e) {
            alert("Error guardando: " + e.message);
        } finally {
            setSaving(false);
        }
    };

    return (
        <>
            <Header title="Calcular Bolo" showBack={true} />
            <main className="page" style={{ paddingBottom: '90px' }}>

                {/* INPUT SECTION */}
                {!result && (
                    <div className="stack fade-in">
                        {/* Glucose */}
                        <div className="form-group">
                            <div className="label-row" style={{ display: 'flex', justifyContent: 'space-between' }}>
                                <span className="label-text">💧 Glucosa Actual</span>
                            </div>
                            <div style={{ position: 'relative' }}>
                                <input
                                    type="number"
                                    value={glucose}
                                    onChange={e => setGlucose(e.target.value)}
                                    placeholder="mg/dL"
                                    className="text-center big-input"
                                    style={{ width: '100%', fontSize: '1.5rem', fontWeight: 800, color: 'var(--primary)', padding: '0.5rem', borderRadius: '8px', border: '1px solid #cbd5e1' }}
                                />
                                <span style={{ position: 'absolute', right: '1rem', top: '1rem', color: 'var(--text-muted)' }}>mg/dL</span>
                            </div>
                            {glucose && !isNaN(parseFloat(glucose)) && (
                                <input type="range" min="40" max="400" value={glucose} onChange={e => setGlucose(e.target.value)} className="w-full mt-2" />
                            )}
                        </div>

                        {/* Date */}
                        <div className="form-group">
                            <label style={{ fontSize: '0.85rem', color: '#64748b' }}>Fecha / Hora</label>
                            <input type="datetime-local" value={date} onChange={e => setDate(e.target.value)} style={{ width: '100%', padding: '0.5rem', borderRadius: '8px', border: '1px solid #cbd5e1' }} />
                        </div>

                        {/* Slot Selector */}
                        <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'center', margin: '1rem 0' }}>
                            <select value={slot} onChange={e => setSlot(e.target.value)} style={{ padding: '0.5rem', borderRadius: '8px', border: '1px solid #cbd5e1', background: '#fff' }}>
                                <option value="breakfast">Desayuno</option>
                                <option value="lunch">Comida</option>
                                <option value="dinner">Cena</option>
                                <option value="snack">Snack</option>
                            </select>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.9rem' }}>
                                <input type="checkbox" checked={correctionOnly} onChange={e => {
                                    setCorrectionOnly(e.target.checked);
                                    if (e.target.checked) setCarbs("0");
                                }} />
                                Solo Corrección
                            </label>
                        </div>

                        {/* Carbs */}
                        <div className={`form-group ${correctionOnly ? 'opacity-50 pointer-events-none' : ''}`}>
                            <div className="label-row"><span className="label-text">🍪 Carbohidratos</span></div>
                            <div style={{ position: 'relative' }}>
                                <input
                                    type="number"
                                    value={carbs}
                                    onChange={e => setCarbs(e.target.value)}
                                    placeholder="0"
                                    className="text-center big-input"
                                    style={{ width: '100%', fontSize: '1.5rem', fontWeight: 800, color: 'var(--text)', padding: '0.5rem', borderRadius: '8px', border: '1px solid #cbd5e1' }}
                                />
                                <span style={{ position: 'absolute', right: '1rem', top: '1rem', color: 'var(--text-muted)' }}>g</span>
                            </div>
                            <div className="carb-presets" style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem', flexWrap: 'wrap', justifyContent: 'center' }}>
                                {[0, 15, 30, 45, 60].map(v => (
                                    <button
                                        key={v}
                                        onClick={() => setCarbs(String(v))}
                                        style={{
                                            padding: '0.3rem 0.8rem', borderRadius: '16px', border: '1px solid #cbd5e1',
                                            background: parseFloat(carbs) === v ? 'var(--primary)' : '#fff',
                                            color: parseFloat(carbs) === v ? '#fff' : '#334155'
                                        }}
                                    >
                                        {v}g
                                    </button>
                                ))}
                            </div>
                        </div>

                        {/* Learning Hint Banner */}
                        {learningHint && (
                            <div className="fade-in" style={{
                                background: (learningHint.suggest_extended && !dualEnabled) ? '#fff7ed' : (learningHint.suggest_extended ? '#f0fdf4' : '#fff7ed'),
                                border: `1px solid ${(learningHint.suggest_extended && !dualEnabled) ? '#fdba74' : (learningHint.suggest_extended ? '#86efac' : '#fdba74')}`,
                                borderRadius: '12px', padding: '0.8rem', marginBottom: '0.5rem',
                                fontSize: '0.85rem', color: '#334155',
                                transition: 'all 0.3s ease'
                            }}>
                                <div style={{
                                    fontWeight: 600,
                                    color: (learningHint.suggest_extended && !dualEnabled) ? '#c2410c' : (learningHint.suggest_extended ? '#15803d' : '#c2410c'),
                                    display: 'flex', alignItems: 'center', gap: '5px', justifyContent: 'space-between'
                                }}>
                                    <span style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                                        🧠 Memoria de Efectos
                                    </span>
                                    {learningHint.suggest_extended && (
                                        <span style={{ fontSize: '0.75rem', padding: '2px 8px', borderRadius: '12px', background: 'rgba(0,0,0,0.05)' }}>
                                            {dualEnabled ? 'Aplicada' : 'Ignorada'}
                                        </span>
                                    )}
                                </div>

                                <div style={{ marginTop: '4px' }}>{learningHint.reason}</div>

                                {learningHint.evidence && (
                                    <div style={{ fontSize: '0.75rem', marginTop: '4px', opacity: 0.8 }}>
                                        Basado en {learningHint.evidence.n} comidas similares.
                                    </div>
                                )}
                            </div>
                        )}

                        {/* Dual Bolus Toggle with Smart Suggestion */}
                        <div className="card" style={{
                            display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '1rem',
                            border: dualEnabled ? '2px solid #3b82f6' : '1px solid #e2e8f0',
                            background: dualEnabled ? '#eff6ff' : '#fff'
                        }}>
                            <div>
                                <div style={{ fontWeight: 600, color: dualEnabled ? '#1d4ed8' : '#0f172a' }}>🌊 Bolo Dual / Extendido</div>
                                {state.tempFat > 15 && (
                                    <div style={{ fontSize: '0.75rem', color: '#b91c1c', marginTop: '4px' }}>
                                        🔥 Alto en grasas ({state.tempFat}g) detectado.
                                    </div>
                                )}
                            </div>
                            <input
                                type="checkbox"
                                checked={dualEnabled}
                                onChange={toggleDual}
                                style={{ transform: 'scale(1.5)', cursor: 'pointer' }}
                            />
                        </div>

                        {/* IOB Banner */}
                        <div style={{ background: '#eff6ff', padding: '1rem', borderRadius: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                            <div>
                                <div style={{ fontWeight: 600, color: '#1e40af' }}>Insulina Activa (IOB)</div>
                                <div style={{ fontSize: '0.8rem', color: '#60a5fa' }}>Se restará del bolo</div>
                            </div>
                            <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#1e40af' }}>
                                {iob !== null ? iob.toFixed(2) : '--'} <span style={{ fontSize: '1rem' }}>U</span>
                            </div>
                        </div>

                        <Button onClick={handleCalculate} disabled={calculating} className="btn-primary" style={{ width: '100%', padding: '1rem', fontSize: '1.1rem' }}>
                            {calculating ? 'Calculando...' : 'Calcular Bolo'}
                        </Button>
                    </div>
                )}

                {/* RESULT SECTION */}
                {result && (
                    <ResultView
                        result={result}
                        onBack={() => setResult(null)}
                        onSave={handleSave}
                        saving={saving}
                    />
                )}

            </main>
            <BottomNav activeTab="bolus" />
        </>
    );
}

function ResultView({ result, onBack, onSave, saving }) {
    // Local state for edit before confirm
    const [finalDose, setFinalDose] = useState(result.upfront_u);

    const later = parseFloat(result.later_u || 0);
    const upfront = parseFloat(finalDose || 0);
    const total = upfront + later;

    return (
        <div className="card result-card fade-in" style={{ border: '2px solid var(--primary)', padding: '1.5rem' }}>
            <div style={{ textAlign: 'center' }}>
                <div className="text-muted" style={{ marginBottom: '0.5rem' }}>Bolo Recomendado</div>

                {/* DUAL BOLUS: Prominent Total Display */}
                {result.kind === 'dual' && (
                    <div style={{
                        background: '#f1f5f9',
                        borderRadius: '12px',
                        padding: '1rem',
                        marginBottom: '1.5rem',
                        border: '1px solid #cbd5e1'
                    }}>
                        <div style={{ fontSize: '0.85rem', fontWeight: 700, color: '#64748b', letterSpacing: '1px' }}>TOTAL</div>
                        <div style={{ fontSize: '3rem', fontWeight: 800, color: '#0f172a', lineHeight: 1 }}>
                            {total % 1 === 0 ? total : total.toFixed(2)} <span style={{ fontSize: '1.5rem', color: '#64748b' }}>U</span>
                        </div>
                    </div>
                )}

                {/* Immediate Input */}
                <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'baseline', gap: '8px' }}>
                    {result.kind === 'dual' && <span style={{ fontSize: '1rem', fontWeight: 600, color: '#64748b' }}>Ahora:</span>}
                    <input
                        type="number"
                        value={finalDose}
                        onChange={e => setFinalDose(e.target.value)}
                        step="0.5"
                        style={{
                            width: '120px', textAlign: 'right',
                            fontSize: result.kind === 'dual' ? '2rem' : '3.5rem',
                            color: 'var(--primary)', fontWeight: 800,
                            border: 'none', borderBottom: '2px dashed var(--primary)',
                            outline: 'none', background: 'transparent'
                        }}
                    />
                    <span style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--primary)' }}>U</span>
                </div>

                {/* Extended Part */}
                {result.kind === 'dual' && (
                    <div style={{ marginTop: '0.5rem', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '5px', color: '#64748b' }}>
                        <span style={{ fontSize: '1rem', fontWeight: 600 }}>Extendido:</span>
                        <span style={{ fontSize: '1.2rem', fontWeight: 700 }}>{result.later_u} U</span>
                        <span style={{ fontSize: '0.9rem' }}>({result.duration_min} min)</span>
                    </div>
                )}
            </div>

            <ul style={{ marginTop: '1.5rem', fontSize: '0.85rem', color: '#64748b', paddingLeft: '1.2rem' }}>
                {result.calc?.explain?.map((line, i) => <li key={i}>{line}</li>)}
            </ul>

            {result.warnings && result.warnings.length > 0 && (
                <div style={{ background: '#fff7ed', color: '#c2410c', padding: '0.8rem', margin: '1rem 0', borderRadius: '8px', fontSize: '0.85rem', border: '1px solid #fed7aa' }}>
                    <strong>⚠️ Atención:</strong>
                    {result.warnings.map((w, i) => <div key={i}>• {w}</div>)}
                </div>
            )}

            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '1.5rem' }}>
                <Button onClick={() => onSave(finalDose)} disabled={saving} style={{ flex: 1, background: 'var(--success)', padding: '1rem', fontSize: '1.1rem' }}>
                    {saving ? 'Guardando...' : '✅ Confirmar'}
                </Button>
                <Button variant="ghost" onClick={onBack} disabled={saving} style={{ flex: 1 }}>
                    Cancelar
                </Button>
            </div>
        </div>
    );
}

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

    // Effect: Load temp carbs (e.g. from favorites / scale)
    useEffect(() => {
        // We use a small timeout to ensure ensure legacy state is ready or passed via props
        // But since we are inside the same window context, we can read global 'state'
        if (state.tempCarbs) {
            setCarbs(String(state.tempCarbs));
            state.tempCarbs = null; // Clear it
        }

        // Auto-enable Dual if fat/protein high
        if (state.tempFat > 15 || state.tempProtein > 20) {
            setDualEnabled(true);
            // We could also show a toast, but the toggle changing state is visible enough
        }
        state.tempFat = null;
        state.tempProtein = null;

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
                    token: nsConfig.token || null
                }
            };

            if (result.kind === 'dual') {
                treatment.notes += ` (Split: ${result.upfront_u} now + ${result.later_u} over ${result.duration_min}m)`;
                // Update global state for HomePage tracking
                state.lastBolusPlan = result.plan;
                // If the user modified the immediate dose, we update the 'now' part of the plan
                state.lastBolusPlan.now_u = finalInsulin;
                import('../modules/core/store').then(({ saveDualPlan }) => saveDualPlan(result.plan));
            }

            const apiRes = await saveTreatment(treatment);

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

                        {/* Dual Bolus Toggle */}
                        <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '1rem', border: '1px solid #e2e8f0' }}>
                            <div style={{ fontWeight: 600 }}>🌊 Bolo Dual / Extendido</div>
                            <input type="checkbox" checked={dualEnabled} onChange={toggleDual} style={{ transform: 'scale(1.5)' }} />
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

    return (
        <div className="card result-card fade-in" style={{ border: '2px solid var(--primary)', padding: '1.5rem' }}>
            <div style={{ textAlign: 'center' }}>
                <div className="text-muted">Bolo Recomendado</div>
                <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'baseline', gap: '5px' }}>
                    <input
                        type="number"
                        value={finalDose}
                        onChange={e => setFinalDose(e.target.value)}
                        step="0.5"
                        style={{ width: '140px', textAlign: 'right', fontSize: '3rem', color: 'var(--primary)', fontWeight: 800, border: 'none', borderBottom: '2px dashed var(--primary)', outline: 'none', background: 'transparent' }}
                    />
                    <span style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--primary)' }}>U</span>
                </div>
                {result.kind === 'dual' && (
                    <div className="text-muted" style={{ marginTop: '0.5rem' }}>
                        + {result.later_u} U extendido ({result.duration_min} min)
                    </div>
                )}
            </div>

            <ul style={{ marginTop: '1rem', fontSize: '0.85rem', color: '#64748b', paddingLeft: '1.2rem' }}>
                {result.calc?.explain?.map((line, i) => <li key={i}>{line}</li>)}
            </ul>

            {result.warnings && result.warnings.length > 0 && (
                <div style={{ background: '#fff7ed', color: '#c2410c', padding: '0.8rem', margin: '1rem 0', borderRadius: '8px', fontSize: '0.85rem', border: '1px solid #fed7aa' }}>
                    <strong>⚠️ Atención:</strong>
                    {result.warnings.map((w, i) => <div key={i}>• {w}</div>)}
                </div>
            )}

            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '1.5rem' }}>
                <Button onClick={() => onSave(finalDose)} disabled={saving} style={{ flex: 1, background: 'var(--success)' }}>
                    {saving ? 'Guardando...' : '✅ Confirmar'}
                </Button>
                <Button variant="ghost" onClick={onBack} disabled={saving} style={{ flex: 1 }}>
                    Cancelar
                </Button>
            </div>
        </div>
    );
}

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
    saveTreatment, getLocalNsConfig, getIOBData,
    getSupplies, updateSupply,
    getFavorites, addFavorite, simulateForecast
} from '../lib/api';
import { showToast } from '../components/ui/Toast';
import { MainGlucoseChart } from '../components/charts/MainGlucoseChart';
import { startRestaurantSession } from '../lib/restaurantApi';
import { navigate } from '../modules/core/router';
import { useStore } from '../hooks/useStore';
import { InjectionSiteSelector, saveInjectionSite, getSiteLabel } from '../components/injection/InjectionSiteSelector';

// Removed local FAV_KEY and helper functions


export default function BolusPage() {
    // State
    const [glucose, setGlucose] = useState('');
    const [carbs, setCarbs] = useState('');
    const [foodName, setFoodName] = useState('');
    const [suggestedStrategy, setSuggestedStrategy] = useState(null); // Strategy from favorites
    const [date, setDate] = useState(() => {
        const now = new Date();
        return new Date(now.getTime() - (now.getTimezoneOffset() * 60000)).toISOString().slice(0, 16);
    });
    const [slot, setSlot] = useState(() => {
        const h = new Date().getHours();
        if (h >= 6 && h < 12) return 'breakfast';
        if (h >= 12 && h < 16) return 'lunch';
        if (h >= 16 && h < 19) return 'snack';
        return 'dinner';
    });
    const [correctionOnly, setCorrectionOnly] = useState(false);
    const [dessertMode, setDessertMode] = useState(false);
    const [dualEnabled, setDualEnabled] = useState(false);
    const [alcoholEnabled, setAlcoholEnabled] = useState(false);
    const [plateItems, setPlateItems] = useState([]);

    // Exercise / Activity State
    const [exerciseEnabled, setExerciseEnabled] = useState(false);
    const [exerciseIntensity, setExerciseIntensity] = useState('moderate');
    const [exerciseMinutes, setExerciseMinutes] = useState(60);

    // Simulation State
    const [simulationMode, setSimulationMode] = useState(false);
    const [predictionData, setPredictionData] = useState(null);
    const [simulating, setSimulating] = useState(false);

    // Favorites State
    const [favorites, setFavorites] = useState([]);

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
    const [orphanCarbs, setOrphanCarbs] = useState(null);
    const [isUsingOrphan, setIsUsingOrphan] = useState(false);

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

            // Favorites
            const favs = await getFavorites();
            if (favs) setFavorites(favs);

            // Recent Treatments (Orphan Carbs Detection)
            try {
                const { fetchTreatments } = await import('../lib/api');
                const treatments = await fetchTreatments({ count: 10 });
                const now = new Date();
                const recentOrphan = treatments.find(t => {
                    const tDate = new Date(t.created_at);
                    const diffMin = (now.getTime() - tDate.getTime()) / 60000;
                    // Orphan = has nutrition (carbs/fat/protein), no insulin, within last 45 mins
                    const hasNutrition = (t.carbs > 0 || t.fat > 0 || t.protein > 0);
                    return hasNutrition && (!t.insulin || t.insulin === 0) && diffMin > 0 && diffMin < 45;
                });
                if (recentOrphan) {
                    setOrphanCarbs(recentOrphan);
                }
            } catch (err) {
                console.warn("Failed to fetch recent treatments for orphan detection", err);
            }

        } catch (e) { console.warn(e); }
    };

    // Effect: Load temp carbs (e.g. from favorites / scale)
    useEffect(() => {
        // We use a small timeout to ensure ensure legacy state is ready or passed via props
        // But since we are inside the same window context, we can read global 'state'
        if (state.tempCarbs) {
            setCarbs(String(state.tempCarbs));
            if (state.tempReason && state.tempReason.startsWith("Fav: ")) {
                setFoodName(state.tempReason.replace("Fav: ", ""));
            }
            state.tempCarbs = null; // Clear it
            state.tempReason = null;
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
        if (state.tempItems) {
            setPlateItems(state.tempItems);
        }

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

    // Strategy Suggestion Logic
    useEffect(() => {
        if (!foodName) {
            setSuggestedStrategy(null);
            return;
        }
        // Match from loaded API favorites
        const match = favorites.find(f => f.name.toLowerCase() === foodName.trim().toLowerCase());
        if (match && match.strategy && match.strategy.type === 'dual') {
            // Only suggest if not already enabled
            if (!dualEnabled) {
                setSuggestedStrategy(match.strategy);
            }
        } else {
            setSuggestedStrategy(null);
        }
    }, [foodName, dualEnabled, favorites]);

    // Simulation Effect (Debounced)
    useEffect(() => {
        if (!simulationMode) {
            setPredictionData(null);
            return;
        }

        const runSim = async () => {
            const bgVal = parseFloat(glucose);
            // If no BG, we can't really simulate well, but maybe with just carbs?
            // Loop needs a starting BG.
            if (isNaN(bgVal)) return;

            setSimulating(true);
            try {
                const currentCarbs = parseFloat(carbs) || 0;

                // Get params
                const mealParams = getCalcParams();
                // If not loaded, retry later or defaults
                const slotParams = mealParams ? mealParams[slot] : { icr: 10, isf: 30 };

                const payload = {
                    start_bg: bgVal,
                    horizon_minutes: 360,
                    params: {
                        isf: slotParams.isf || 30,
                        icr: slotParams.icr || 10,
                        dia_minutes: (mealParams?.dia_hours || 4) * 60,
                        carb_absorption_minutes: 180
                    },
                    events: {
                        boluses: [], // We simulate "What if I take this dose?"
                        // Actually, we don't know the dose yet unless user confirms?
                        // Loop usually simulates "What if I do nothing" vs "What if I take Rec. Dose".
                        // For now, let's simulate "Net Effect of Carbs" (User hasn't entered insulin yet).
                        // OR maybe we can estimate insulin? 
                        // Let's sim Carbs Only first, as that's the input we have.
                        // Usage: User enters 50g carbs -> Graph shoots up.
                        // Then User enters "Insulin" manually?
                        // The UI doesn't have an "Insulin Input" field in the first stage (Calculadora). 
                        // It calculates it for you.
                        // So we should simulate "Carbs Only" to show the spike risk.
                        carbs: currentCarbs > 0 ? [{
                            time_offset_min: 0,
                            grams: currentCarbs
                        }] : []
                    }
                };

                const res = await simulateForecast(payload);
                setPredictionData(res);
            } catch (err) {
                console.warn("Forecast failed", err);
            } finally {
                setSimulating(false);
            }
        };

        const timer = setTimeout(runSim, 800);
        return () => clearTimeout(timer);
    }, [simulationMode, glucose, carbs, slot]);

    const applyStrategy = () => {
        if (suggestedStrategy) {
            setDualEnabled(true);
            setSuggestedStrategy(null);
        }
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
            if (bgVal < 0 || carbsVal < 0) {
                throw new Error("Los valores no pueden ser negativos.");
            }

            const mealParams = getCalcParams();
            if (!mealParams) throw new Error("No hay configuración de ratios.");

            const slotParams = mealParams[slot];
            if (!slotParams?.icr || !slotParams?.isf || !slotParams?.target) {
                throw new Error(`Faltan datos para el horario '${slot}'.`);
            }

            // Sick Mode Logic
            const isSick = localStorage.getItem('sick_mode_enabled') === 'true';
            let finalIcr = slotParams.icr;
            let finalIsf = slotParams.isf;

            if (isSick) {
                // Increase aggressiveness by ~20% means requiring less carbs/mgdl per unit.
                // Factor = 1 / 1.2 ~= 0.83
                finalIcr = finalIcr * 0.83;
                finalIsf = finalIsf * 0.83;
            }

            const payload = {
                carbs_g: correctionOnly ? 0 : carbsVal,
                bg_mgdl: isNaN(bgVal) ? null : bgVal,
                meal_slot: slot,
                target_mgdl: slotParams.target,
                cr_g_per_u: finalIcr,
                isf_mgdl_per_u: finalIsf,
                dia_hours: mealParams.dia_hours || 4.0,
                round_step_u: mealParams.round_step_u || 0.5,
                max_bolus_u: mealParams.max_bolus_u || 15,
                ignore_iob_for_meal: dessertMode,
                exercise: {
                    planned: exerciseEnabled,
                    minutes: exerciseEnabled ? (parseInt(exerciseMinutes) || 0) : 0,
                    intensity: exerciseIntensity
                },
            };

            let splitSettings = getSplitSettings() || {};
            if (dualEnabled) splitSettings.enabled = true;
            else splitSettings.enabled = false;

            // SAFETY OVERRIDE FOR ALCOHOL
            if (alcoholEnabled && dualEnabled) {
                splitSettings.duration_min = 240; // 4 hours
                splitSettings.later_after_min = 240;
                showToast("🍷 Alcohol: Segunda dosis retrasada a 4h por seguridad.", "info", 4000);
            }

            const useSplit = (dualEnabled && !correctionOnly && carbsVal > 0);
            const res = await calculateBolusWithOptionalSplit(payload, useSplit ? splitSettings : null);

            // Inject Sick Mode Warnings
            if (isSick) {
                res.warnings = res.warnings || [];
                res.warnings.push("⚠️ Modo Enfermedad: Dosis aumentada un 20%.");
                if (bgVal > 250) {
                    res.warnings.push("🧪 ALERTA: Glucosa alta. Revisa CETONAS.");
                }
            }

            setResult(res);
        } catch (e) {
            alert("Error: " + e.message);
        } finally {
            setCalculating(false);
        }
    };

    const handleSave = async (confirmedDose, siteId) => {
        setSaving(true);
        try {
            const finalInsulin = parseFloat(confirmedDose);
            if (isNaN(finalInsulin) || finalInsulin < 0) throw new Error("Dosis inválida");

            const customDate = new Date(date);

            const treatment = {
                eventType: "Meal Bolus",
                created_at: customDate.toISOString(),
                carbs: isUsingOrphan ? 0 : (parseFloat(carbs) || 0),
                fat: isUsingOrphan ? (orphanCarbs.fat || 0) : (mealMetaRef.current?.fat || 0),
                protein: isUsingOrphan ? (orphanCarbs.protein || 0) : (mealMetaRef.current?.protein || 0),
                insulin: finalInsulin,
                enteredBy: state.user?.username || "BolusAI",
                notes: `BolusAI: ${result.kind === 'dual' ? 'Dual' : 'Normal'}. Gr: ${carbs}${isUsingOrphan ? ' (Sincronizado)' : ''}. BG: ${glucose}. ${foodName ? 'Comida: ' + foodName + '.' : ''} ${alcoholEnabled ? 'Alcohol Detected.' : ''} ${plateItems.length > 0 ? 'Items: ' + plateItems.map(i => i.name).join(', ') : ''}`,
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
                treatment.notes += ` (Split: ${finalInsulin} now + ${result.later_u} delayed ${result.duration_min}m)`;
                // Update global state for HomePage tracking
                state.lastBolusPlan = {
                    ...result.plan,
                    upfront_u: finalInsulin, // Update plan with edited value
                    created_at_ts: Date.now()
                };
                import('../modules/core/store').then(({ saveDualPlan }) => saveDualPlan(state.lastBolusPlan));
            }

            // Save Injection Site History (ONLY if insulin > 0)
            if (siteId && finalInsulin > 0) {
                saveInjectionSite('rapid', siteId);
                treatment.notes += ` - Sitio: ${getSiteLabel('rapid', siteId)}`;
            }

            const apiRes = await saveTreatment(treatment);

            // Decrement Needle Stock (ONLY if insulin > 0)
            if (finalInsulin > 0) {
                try {
                    const supplies = await getSupplies();
                    const needles = supplies.find(s => s.key === 'supplies_needles');
                    if (needles && needles.quantity > 0) {
                        await updateSupply('supplies_needles', needles.quantity - 1);
                    }
                } catch (err) {
                    console.warn("Failed to update stock:", err);
                }
            }

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

                showToast("✅ Bolo guardado. Iniciando sesión de restaurante...", "success");
                setTimeout(() => navigate('#/restaurant'), 1000);
                return;
            }

            let msg = "Bolo registrado con éxito (Local).";
            if (apiRes && apiRes.nightscout) {
                if (apiRes.nightscout.uploaded) {
                    msg = "✅ Bolo guardado (Local + Nightscout).";
                    showToast(msg, "success");
                } else {
                    msg = "⚠️ Guardado SOLO local. NS Error: " + (apiRes.nightscout.error || "?");
                    showToast(msg, "warning", 5000);
                }
            } else {
                showToast(msg, "success");
            }

            setTimeout(() => navigate('#/'), 1000);

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

                        {/* Orphan Carbs Alert */}
                        {orphanCarbs && !isUsingOrphan && (
                            <div className="fade-in" style={{
                                background: '#f0fdf4', border: '1px solid #86efac',
                                borderRadius: '12px', padding: '1rem', marginBottom: '1rem',
                                display: 'flex', flexDirection: 'column', gap: '8px'
                            }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#15803d', fontWeight: 700 }}>
                                    <span>🥗 Ingesta Detectada</span>
                                    <span style={{ fontSize: '0.75rem', fontWeight: 400, background: 'rgba(0,0,0,0.05)', padding: '2px 8px', borderRadius: '10px' }}>
                                        hace {Math.round((new Date() - new Date(orphanCarbs.created_at)) / 60000)} min
                                    </span>
                                </div>
                                <div style={{ fontSize: '0.9rem', color: '#166534' }}>
                                    Se han detectado datos externos: <strong>{orphanCarbs.carbs || 0}g HC</strong>
                                    {(orphanCarbs.fat > 0 || orphanCarbs.protein > 0) && (
                                        <span>, {orphanCarbs.fat || 0}g Grasas, {orphanCarbs.protein || 0}g Prot.</span>
                                    )}

                                    {(orphanCarbs.carbs >= 50 || orphanCarbs.fat >= 15 || orphanCarbs.protein >= 20) && (
                                        <div style={{ marginTop: '5px', fontWeight: 600, color: '#15803d' }}>
                                            💡 {orphanCarbs.fat >= 15 ? 'Muchas grasas detectadas.' : 'Cantidad alta detectada.'} Se recomienda <strong>Bolo Dual</strong>.
                                        </div>
                                    )}
                                </div>
                                <div style={{ display: 'flex', gap: '10px' }}>
                                    <Button
                                        onClick={() => {
                                            setCarbs(String(orphanCarbs.carbs || 0));
                                            setIsUsingOrphan(true);
                                            const needsDual = (orphanCarbs.carbs >= 50 || orphanCarbs.fat >= 15 || orphanCarbs.protein >= 20);
                                            if (needsDual) {
                                                setDualEnabled(true);
                                                showToast("✅ Datos aplicados y Bolo Dual activado por grasas/HC.", "success");
                                            } else {
                                                showToast("✅ Usando datos sincronizados.", "success");
                                            }
                                        }}
                                        style={{ background: '#22c55e', color: '#fff', fontSize: '0.85rem', padding: '6px 12px' }}
                                    >
                                        Usar Datos {(orphanCarbs.carbs >= 50 || orphanCarbs.fat >= 15 || orphanCarbs.protein >= 20) ? '+ Dual' : ''}
                                    </Button>
                                    <Button
                                        onClick={() => setOrphanCarbs(null)}
                                        variant="outline"
                                        style={{ fontSize: '0.85rem', padding: '6px 12px' }}
                                    >
                                        Ignorar
                                    </Button>
                                </div>
                            </div>
                        )}

                        {isUsingOrphan && (
                            <div className="fade-in" style={{
                                background: '#eff6ff', border: '1px solid #3b82f6',
                                borderRadius: '12px', padding: '0.8rem', marginBottom: '1rem',
                                display: 'flex', justifyContent: 'space-between', alignItems: 'center'
                            }}>
                                <div style={{ fontSize: '0.85rem', color: '#1e40af' }}>
                                    🔗 Vinculado a {orphanCarbs.carbs}g externos. No se duplicarán.
                                </div>
                                <button
                                    onClick={() => setIsUsingOrphan(false)}
                                    style={{ background: 'none', border: 'none', color: '#3b82f6', fontWeight: 600, fontSize: '0.8rem', cursor: 'pointer' }}
                                >
                                    Desvincular
                                </button>
                            </div>
                        )}





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

                        {/* Smart Food Input */}
                        <div className="form-group">
                            <div className="label-row"><span className="label-text">🍽️ ¿Qué vas a comer? (Opcional)</span></div>
                            <FoodSmartAutocomplete
                                value={foodName}
                                onChange={setFoodName}
                                favorites={favorites} // Pass API favorites
                                onSelect={(item) => {
                                    setFoodName(item.name);
                                    setCarbs(String(item.carbs));
                                }}
                            />

                            {/* Strategy Suggestion */}
                            {suggestedStrategy && (
                                <div className="fade-in" style={{
                                    marginTop: '0.5rem', background: '#eff6ff',
                                    border: '1px dashed #3b82f6', borderRadius: '8px',
                                    padding: '0.8rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between'
                                }}>
                                    <div style={{ fontSize: '0.85rem', color: '#1e3a8a', paddingRight: '10px' }}>
                                        💡 Con <strong>{foodName}</strong> sueles usar <strong>Bolo Dual</strong>.
                                    </div>
                                    <Button onClick={applyStrategy} style={{ fontSize: '0.75rem', padding: '5px 10px', height: 'auto' }}>
                                        Aplicar
                                    </Button>
                                    <div onClick={() => setSuggestedStrategy(null)} style={{ cursor: 'pointer', marginLeft: '10px', fontSize: '1.2rem' }}>×</div>
                                </div>
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
                                    if (e.target.checked) {
                                        setCarbs("0");
                                        setDessertMode(false);
                                    }
                                }} />
                                Solo Corrección
                            </label>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.9rem' }}>
                                <input type="checkbox" checked={dessertMode} onChange={e => {
                                    setDessertMode(e.target.checked);
                                    if (e.target.checked) setCorrectionOnly(false);
                                }} />
                                Postre (Ignorar IOB)
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

                        {/* Plate Summary */}
                        {plateItems.length > 0 && (
                            <div style={{ marginTop: '-10px', marginBottom: '1rem', padding: '0.8rem', background: '#f8fafc', borderRadius: '12px', border: '1px solid #e2e8f0' }}>
                                <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#64748b', marginBottom: '0.5rem', textTransform: 'uppercase' }}>
                                    CONTENIDO DEL PLATO
                                </div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                    {plateItems.map((item, idx) => (
                                        <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', color: '#334155' }}>
                                            <span>{item.amount && item.amount < 10 ? `${item.amount}x` : `•`} {item.name}</span>
                                            <span style={{ fontWeight: 600, color: '#64748b' }}>
                                                {item.carbs ? Math.round(item.carbs) : 0}g
                                            </span>
                                        </div>
                                    ))}
                                    <div style={{ borderTop: '1px dashed #cbd5e1', paddingTop: '6px', marginTop: '4px', display: 'flex', justifyContent: 'space-between', fontSize: '0.9rem', fontWeight: 800, color: '#1e293b' }}>
                                        <span>Total</span>
                                        <span>{plateItems.reduce((acc, i) => acc + (i.carbs || 0), 0).toFixed(0)}g</span>
                                    </div>
                                </div>
                            </div>
                        )}


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

                        {/* Alcohol Toggle */}
                        <div className="card" style={{
                            display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '1rem',
                            border: alcoholEnabled ? '2px solid #8b5cf6' : '1px solid #e2e8f0',
                            background: alcoholEnabled ? '#f5f3ff' : '#fff',
                            marginTop: '0.5rem'
                        }}>
                            <div>
                                <div style={{ fontWeight: 600, color: alcoholEnabled ? '#6d28d9' : '#0f172a' }}>🍷 Alcohol</div>
                                <div style={{ fontSize: '0.8rem', color: '#64748b' }}>
                                    Retrasa el pico de glucosa (8h)
                                </div>
                            </div>
                            <input
                                type="checkbox"
                                checked={alcoholEnabled}
                                onChange={() => setAlcoholEnabled(!alcoholEnabled)}
                                style={{ transform: 'scale(1.5)', cursor: 'pointer' }}
                            />
                        </div>

                        {/* Exercise Card */}
                        <div className="card" style={{
                            display: 'flex', flexDirection: 'column', gap: '0.8rem', padding: '1rem',
                            border: exerciseEnabled ? '2px solid #10b981' : '1px solid #e2e8f0',
                            background: exerciseEnabled ? '#ecfdf5' : '#fff',
                            marginTop: '1rem'
                        }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <div>
                                    <div style={{ fontWeight: 600, color: exerciseEnabled ? '#047857' : '#0f172a' }}>🏃‍♂️ Actividad Física</div>
                                    <div style={{ fontSize: '0.8rem', color: exerciseEnabled ? '#059669' : '#64748b' }}>
                                        {exerciseEnabled ? 'Se reducirá el bolo' : 'Ajuste por Ejercicio'}
                                    </div>
                                </div>
                                <input
                                    type="checkbox"
                                    checked={exerciseEnabled}
                                    onChange={() => setExerciseEnabled(!exerciseEnabled)}
                                    style={{ transform: 'scale(1.5)', cursor: 'pointer' }}
                                />
                            </div>

                            {exerciseEnabled && (
                                <div className="fade-in" style={{ borderTop: '1px dashed #6ee7b7', paddingTop: '0.8rem' }}>
                                    <div style={{ fontSize: '0.85rem', marginBottom: '0.4rem', color: '#065f46' }}>Intensidad</div>
                                    <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
                                        {['low', 'moderate', 'high'].map(lvl => (
                                            <button
                                                key={lvl}
                                                onClick={() => setExerciseIntensity(lvl)}
                                                style={{
                                                    flex: 1, padding: '0.4rem', borderRadius: '8px',
                                                    border: '1px solid',
                                                    borderColor: exerciseIntensity === lvl ? '#059669' : '#d1fae5',
                                                    background: exerciseIntensity === lvl ? '#059669' : '#fff',
                                                    color: exerciseIntensity === lvl ? '#fff' : '#047857',
                                                    fontSize: '0.85rem', textTransform: 'capitalize'
                                                }}
                                            >
                                                {lvl === 'low' ? 'Suave' : lvl === 'moderate' ? 'Moderada' : 'Intensa'}
                                            </button>
                                        ))}
                                    </div>

                                    <div style={{ fontSize: '0.85rem', marginBottom: '0.4rem', color: '#065f46' }}>Duración (min)</div>
                                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                        {[30, 60, 90, 120].map(m => (
                                            <button
                                                key={m}
                                                onClick={() => setExerciseMinutes(m)}
                                                style={{
                                                    padding: '0.3rem 0.6rem', borderRadius: '8px',
                                                    border: '1px solid',
                                                    borderColor: exerciseMinutes === m ? '#059669' : '#d1fae5',
                                                    background: exerciseMinutes === m ? '#10b981' : '#fff',
                                                    color: exerciseMinutes === m ? '#fff' : '#047857',
                                                    fontSize: '0.85rem'
                                                }}
                                            >
                                                {m}
                                            </button>
                                        ))}
                                        <input
                                            type="number"
                                            value={exerciseMinutes}
                                            onChange={(e) => setExerciseMinutes(parseInt(e.target.value) || 0)}
                                            style={{ width: '60px', padding: '0.3rem', borderRadius: '8px', border: '1px solid #d1fae5', textAlign: 'center' }}
                                        />
                                    </div>
                                </div>
                            )}
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
                        slot={slot} // Pass slot for fallback
                        onBack={() => setResult(null)}
                        onSave={handleSave}
                        saving={saving}
                        currentCarbs={carbs}
                        foodName={foodName}
                        favorites={favorites} // Pass favorites for checking existence
                        onFavoriteAdded={(newFav) => setFavorites(prev => [...prev, newFav])} // Optimistic update or reload
                        alcoholEnabled={alcoholEnabled}
                    />
                )}

            </main>
            <BottomNav activeTab="bolus" />
        </>
    );
}

function ResultView({ result, slot, onBack, onSave, saving, currentCarbs, foodName, favorites, onFavoriteAdded, alcoholEnabled }) {
    // Local state for edit before confirm
    const [finalDose, setFinalDose] = useState(result.upfront_u);
    const [injectionSite, setInjectionSite] = useState(null);

    // Check if entered food is new
    const [isNewFav, setIsNewFav] = useState(false);
    const [saveFav, setSaveFav] = useState(false);

    // SAFETY CHECK FOR ALCOHOL SIMPLE BOLUS
    const showAlcoholWarning = alcoholEnabled && result.kind === 'normal';

    useEffect(() => {
        if (foodName && foodName.trim().length > 2) {
            const exists = favorites.some(f => f.name.toLowerCase() === foodName.toLowerCase());
            if (!exists) {
                setIsNewFav(true);
                setSaveFav(true);
            }
        }
    }, [foodName, favorites]);

    const [predictionData, setPredictionData] = useState(null);
    const [simulating, setSimulating] = useState(false);

    // Auto-Simulation Debounced
    useEffect(() => {
        const timer = setTimeout(() => {
            const dose = parseFloat(finalDose);
            if (!isNaN(dose) && dose >= 0) {
                runSimulation(dose, later, parseFloat(currentCarbs));
            }
        }, 800);
        return () => clearTimeout(timer);
    }, [finalDose]);

    const runSimulation = async (doseNow, doseLater, carbsVal) => {
        setSimulating(true);
        setPredictionData(null);
        try {
            // Get glucose from result (calculated context) OR manual fallback if needed?
            // Usually result.glucose has the used glucose.
            // If missing (e.g. user entered carbs only without BG), default to Target or 100 to show "Relative" effect.
            let bgVal = result.glucose?.mgdl;

            if (!bgVal || bgVal <= 0) {
                // Fallback to target for simulation baseline
                bgVal = result.used_params?.target_mgdl || 100;
            }

            console.log("DEBUG RESULT OBJ:", result);
            let params = result.calc?.used_params || result.calc?.usedParams || result.used_params || result.usedParams;

            if (!params) {
                console.warn("Params missing in result, trying fallback from store...");
                const allParams = getCalcParams();
                if (allParams && slot) {
                    params = allParams[slot];
                    // Normalise store format to expected format if needed, or rely on loose access below
                    // Store has { icr, isf, target ... }
                    // Code below expects { isf_mgdl_per_u, ... }
                    // We need to map it if we use fallback.
                    if (params) {
                        params = {
                            isf_mgdl_per_u: params.isf,
                            cr_g_per_u: params.icr,
                            dia_hours: allParams.dia_hours || 4,
                            insulin_model: allParams.insulin_model // Fallback mapping
                        };
                    }
                }
            }

            if (!params) throw new Error("Parámetros de cálculo no disponibles.");

            // Robust extraction with fallbacks for legacy/alternative naming
            // The simulation crashing to LOW usually implies Default ICR (10) was used instead of Custom (e.g. 2.5)
            // causing the insulin (calculated for 2.5) to crush the carbs (simulated for 10).
            const isf = params.isf_mgdl_per_u || params.isfMgdlPerU || params.isf || 30;
            const icr = params.cr_g_per_u || params.crGPerU || params.icr || 10;
            const dia = params.dia_hours || params.diaHours || 4;

            console.log("Input Params for Sim:", { isf, icr, dia });

            // Build events
            const boluses = [];

            // Immediate
            const nowU = isNaN(doseNow) ? 0 : doseNow;
            if (nowU > 0) boluses.push({ time_offset_min: 0, units: nowU });

            // This is the most critical check.

            const cVal = isNaN(carbsVal) ? 0 : carbsVal;
            const events = {
                boluses: boluses,
                carbs: cVal > 0 ? [{ time_offset_min: 0, grams: cVal }] : []
            };

            const payload = {
                start_bg: bgVal,
                horizon_minutes: 360,
                params: {
                    isf: isf,
                    icr: icr,
                    dia_minutes: dia * 60,
                    carb_absorption_minutes: 180,
                    insulin_model: params.insulin_model || 'linear'
                },
                events: events
            };

            console.log("🚀 Simulation Payload:", JSON.stringify(payload, null, 2));

            const res = await simulateForecast(payload);
            console.log("✅ Simulation Result:", res);
            setPredictionData(res);

            // Notification logic requested by user
            if (res && res.summary) {
                const min = Math.round(res.summary.min_bg);
                if (min < 70) {
                    showToast(`⚠️ RIESGO: Mínimo previsto ${min} mg/dL`, "warning", 4000);
                    // TRIGGER HEADER ALARM
                    localStorage.setItem('forecast_warning', 'true');
                    localStorage.setItem('forecast_warning_dismissed_at', '0');
                    window.dispatchEvent(new Event('forecast-update'));
                } else {
                    // CLEAR ALARM if safe
                    localStorage.removeItem('forecast_warning');
                    window.dispatchEvent(new Event('forecast-update'));
                }
            }

        } catch (err) {
            console.warn("Forecast Sim error", err);
        } finally {
            setSimulating(false);
        }
    };

    const handleConfirm = async () => {
        if (saveFav && isNewFav && foodName) {
            try {
                // Save to API
                const newFav = await addFavorite(foodName, parseFloat(currentCarbs));
                if (onFavoriteAdded) onFavoriteAdded(newFav);
            } catch (err) {
                console.error("Error saving favorite:", err);
                alert("No se pudo guardar el favorito, pero el bolo continuará.");
            }
        }
        onSave(finalDose, injectionSite);
    };

    const later = parseFloat(result.later_u || 0);
    const upfront = parseFloat(finalDose || 0);
    const total = upfront + later;

    return (
        <div className="card result-card fade-in" style={{ border: '2px solid var(--primary)', padding: '1.5rem' }}>
            {showAlcoholWarning && (
                <div style={{
                    background: '#fff7ed', border: '1px solid #fdba74', borderRadius: '12px',
                    padding: '1rem', marginBottom: '1rem', display: 'flex', gap: '10px'
                }}>
                    <div style={{ fontSize: '1.5rem' }}>🍷💡</div>
                    <div>
                        <div style={{ fontWeight: 700, color: '#c2410c' }}>Sugerencia: Usa Bolo Dividido</div>
                        <div style={{ fontSize: '0.85rem', color: '#ea580c', marginTop: '4px' }}>
                            Con alcohol, lo más seguro es <strong>dividir la dosis</strong> (menos insulina ahora, más luego).
                            <br />
                            Si prefieres bolo simple, <strong>espera 30 min</strong> antes de inyectar.
                        </div>
                    </div>
                </div>
            )}

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

                {/* Pre-Bolus Timer / Advisory */}
                <PreBolusTimer />

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


                {(predictionData || simulating) && (
                    <div className="fade-in" style={{
                        padding: '0.8rem',
                        marginBottom: '1.5rem',
                        borderRadius: '12px',
                        background: (!predictionData || simulating) ? '#f8fafc' : (predictionData.summary.min_bg < 70 ? '#fef2f2' : '#f0fdf4'),
                        border: (!predictionData || simulating) ? '1px dashed #cbd5e1' : (predictionData.summary.min_bg < 70 ? '1px solid #fecaca' : '1px solid #bbf7d0'),
                        display: 'flex', flexDirection: 'column', alignItems: 'center', transition: 'all 0.3s ease'
                    }}>
                        {!simulating && predictionData && predictionData.summary.min_bg < 70 && (
                            <div style={{
                                color: '#b91c1c', fontWeight: 800, fontSize: '0.85rem',
                                marginBottom: '0.8rem', width: '100%', textAlign: 'center',
                                background: 'rgba(254, 202, 202, 0.3)', padding: '6px',
                                borderRadius: '6px', border: '1px solid #fecaca'
                            }}>
                                ⚠️ SE ESPERA BAJA
                            </div>
                        )}

                        <div style={{ display: 'flex', justifyContent: 'space-around', alignItems: 'center', width: '100%' }}>
                            {simulating ? (
                                <div style={{ color: '#64748b', fontSize: '0.9rem', fontStyle: 'italic' }}>🔮 Calculando futuro...</div>
                            ) : (
                                <>
                                    <div style={{ textAlign: "center" }}>
                                        <div style={{ fontSize: "0.75rem", color: "#64748b", textTransform: 'uppercase', letterSpacing: '0.5px' }}>Mínimo</div>
                                        <div style={{ fontSize: "1.2rem", fontWeight: 800, color: predictionData.summary.min_bg < 70 ? '#dc2626' : '#166534' }}>
                                            {Math.round(predictionData.summary.min_bg)}
                                        </div>
                                    </div>
                                    <div style={{ height: '30px', width: '1px', background: '#cbd5e1' }}></div>
                                    <div style={{ textAlign: "center" }}>
                                        <div style={{ fontSize: "0.75rem", color: "#64748b", textTransform: 'uppercase', letterSpacing: '0.5px' }}>Final (6h)</div>
                                        <div style={{ fontSize: "1.2rem", fontWeight: 800, color: "#334155" }}>
                                            {Math.round(predictionData.summary.ending_bg)}
                                        </div>
                                    </div>
                                </>
                            )}
                        </div>
                    </div>
                )}

                {/* Extended Part */}
                {result.kind === 'dual' && (
                    <div style={{ marginTop: '0.5rem', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '5px', color: '#64748b' }}>
                        <span style={{ fontSize: '1rem', fontWeight: 600 }}>Extendido:</span>
                        <span style={{ fontSize: '1.2rem', fontWeight: 700 }}>{result.later_u} U</span>
                        <span style={{ fontSize: '0.9rem' }}>({result.duration_min} min)</span>
                    </div>
                )}
            </div>

            {/* Safety Alerts */}
            {result.calc?.explain?.filter(l => l.includes('⛔') || l.includes('⚠️')).map((line, i) => (
                <div key={'alert-' + i} style={{
                    background: line.includes('⛔') ? '#fee2e2' : '#fff7ed',
                    color: line.includes('⛔') ? '#991b1b' : '#c2410c',
                    padding: '0.75rem', borderRadius: '8px', marginBottom: '1rem',
                    fontWeight: 'bold', border: line.includes('⛔') ? '2px solid #ef4444' : '1px solid #fdba74'
                }}>
                    {line}
                </div>
            ))}

            <ul style={{ marginTop: '1.5rem', fontSize: '0.85rem', color: '#64748b', paddingLeft: '1.2rem' }}>
                {result.calc?.explain?.filter(l => !l.includes('⛔') && !l.includes('⚠️')).map((line, i) => <li key={i}>{line}</li>)}
            </ul>

            {result.warnings && result.warnings.length > 0 && (
                <div style={{ background: '#fff7ed', color: '#c2410c', padding: '0.8rem', margin: '1rem 0', borderRadius: '8px', fontSize: '0.85rem', border: '1px solid #fed7aa' }}>
                    <strong>⚠️ Atención:</strong>
                    {result.warnings.map((w, i) => <div key={i}>• {w}</div>)}
                </div>
            )}

            {isNewFav && (
                <div style={{ margin: '1rem 0', background: '#f0fdf4', padding: '0.8rem', borderRadius: '8px', border: '1px dashed #4ade80' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '0.9rem', color: '#166534', cursor: 'pointer' }}>
                        <input type="checkbox" checked={saveFav} onChange={e => setSaveFav(e.target.checked)} style={{ transform: 'scale(1.2)' }} />
                        <div>
                            <strong>¿Guardar como favorito?</strong>
                            <div style={{ fontSize: '0.8rem', opacity: 0.8 }}>Aprendera que "{foodName}" son {currentCarbs}g.</div>
                        </div>
                    </label>
                </div>
            )}

            <div style={{ margin: '1rem 0' }}>
                <InjectionSiteSelector
                    type="rapid"
                    selected={injectionSite}
                    onSelect={setInjectionSite}
                />
            </div>

            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '1.5rem' }}>
                <Button onClick={handleConfirm} disabled={saving} style={{ flex: 1, background: 'var(--success)', padding: '1rem', fontSize: '1.1rem' }}>
                    {saving ? 'Guardando...' : '✅ Confirmar'}
                </Button>
                <Button variant="ghost" onClick={onBack} disabled={saving} style={{ flex: 1 }}>
                    Cancelar
                </Button>
            </div>
        </div>
    );
}

function FoodSmartAutocomplete({ value, onChange, onSelect, favorites = [] }) {
    const [suggestions, setSuggestions] = useState([]);
    const [bestMatch, setBestMatch] = useState('');

    const acceptMatch = () => {
        if (!bestMatch) return;
        const item = favorites.find(f => f.name === bestMatch);
        if (item) {
            onSelect(item);
            setBestMatch('');
            setSuggestions([]);
        }
    };

    // Helper for accent-insensitive comparison
    const normalize = (str) => str.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

    // Suggest based on input
    useEffect(() => {
        if (!value || value.length < 1) {
            setSuggestions([]);
            setBestMatch('');
            return;
        }

        const normVal = normalize(value.trim());

        // 1. Ghost Match: Must start with input (accent-insensitive)
        const prefixMatch = favorites.find(f => normalize(f.name).startsWith(normVal));
        if (prefixMatch) {
            setBestMatch(prefixMatch.name);
        } else {
            setBestMatch('');
        }

        // 2. Dropdown Match: Contains input (accent-insensitive)
        const matches = favorites.filter(f => normalize(f.name).includes(normVal));
        setSuggestions(matches.slice(0, 5)); // Increased limit to 5
    }, [value, favorites]);

    const handleKeyDown = (e) => {
        if ((e.key === 'Enter' || e.key === 'Tab') && bestMatch) {
            e.preventDefault();
            acceptMatch();
        }
    };

    return (
        <div style={{ position: 'relative' }}>
            <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                {/* Ghost Input Layer */}
                <input
                    type="text"
                    readOnly
                    value={bestMatch}
                    style={{
                        position: 'absolute', top: 0, left: 0, width: '100%', height: '100%',
                        color: '#94a3b8',
                        background: 'transparent',
                        border: '1px solid transparent',
                        borderRadius: '8px',
                        padding: '0.5rem',
                        fontSize: '1rem',
                        pointerEvents: 'none',
                        zIndex: 1
                    }}
                    tabIndex={-1}
                />

                {/* Real Input Layer */}
                <input
                    type="text"
                    placeholder={bestMatch ? "" : "Ej: Pizza, Manzana..."}
                    value={value}
                    onChange={e => onChange(e.target.value)}
                    onKeyDown={handleKeyDown}
                    style={{
                        width: '100%',
                        position: 'relative',
                        zIndex: 2,
                        background: 'transparent',
                        border: '1px solid #cbd5e1',
                        borderRadius: '8px',
                        padding: '0.5rem',
                        fontSize: '1rem',
                        color: 'var(--text)'
                    }}
                    autoComplete="off"
                />

                {/* Mobile 'Use' Button */}
                {bestMatch && bestMatch.toLowerCase() !== value.toLowerCase() && (
                    <div
                        onClick={acceptMatch}
                        style={{
                            position: 'absolute',
                            right: '10px',
                            zIndex: 3,
                            color: 'var(--primary)',
                            cursor: 'pointer',
                            fontWeight: 'bold',
                            background: '#eff6ff',
                            padding: '2px 8px',
                            borderRadius: '4px',
                            border: '1px solid #bfdbfe',
                            fontSize: '0.8rem'
                        }}
                    >
                        ↲ Usar
                    </div>
                )}
            </div>

            {/* Dropdown Suggestions */}
            {suggestions.length > 0 && (
                <div style={{
                    position: 'absolute', top: '105%', left: 0, right: 0,
                    background: '#fff', border: '1px solid #cbd5e1',
                    borderRadius: '8px', zIndex: 10, boxShadow: '0 4px 6px rgba(0,0,0,0.1)'
                }}>
                    {suggestions.map(s => {
                        const matchIndex = s.name.toLowerCase().indexOf(value.toLowerCase());
                        const before = matchIndex >= 0 ? s.name.slice(0, matchIndex) : s.name;
                        const match = matchIndex >= 0 ? s.name.slice(matchIndex, matchIndex + value.length) : "";
                        const after = matchIndex >= 0 ? s.name.slice(matchIndex + value.length) : "";

                        return (
                            <div
                                key={s.id}
                                onClick={() => {
                                    onSelect(s);
                                    setSuggestions([]);
                                    setBestMatch('');
                                }}
                                style={{
                                    padding: '0.8rem', borderBottom: '1px solid #f1f5f9',
                                    cursor: 'pointer', display: 'flex', justifyContent: 'space-between',
                                    background: bestMatch === s.name ? '#f0f9ff' : 'transparent'
                                }}
                            >
                                <span>{before}<strong>{match}</strong>{after}</span>
                                <span style={{ fontWeight: 700, color: 'var(--primary)' }}>{s.carbs}g</span>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

function PreBolusTimer() {
    const [waitMin, setWaitMin] = useState(0);
    const [eatTime, setEatTime] = useState(null);
    const [name, setName] = useState("");

    useEffect(() => {
        import('../modules/core/store').then(({ getCalcParams }) => {
            const p = getCalcParams();
            const min = p?.insulin?.pre_bolus_min || 0;
            setWaitMin(min);
            setName(p?.insulin?.name || "");

            if (min > 0) {
                const now = new Date();
                const eatAt = new Date(now.getTime() + min * 60000);
                setEatTime(eatAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
            }
        });
    }, []);

    if (waitMin <= 0) return null;

    return (
        <div style={{ textAlign: 'center', marginBottom: '1rem' }}>
            <div style={{
                background: '#e0f2fe',
                color: '#0369a1',
                padding: '0.6rem 1rem',
                borderRadius: '20px',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '8px',
                fontSize: '0.9rem',
                fontWeight: 600,
                border: '1px solid #bae6fd'
            }}>
                <span>⏳ Espera {waitMin} min {name ? `(${name})` : ''}</span>
                {eatTime && <span style={{ opacity: 0.8, fontWeight: 400 }}>→ Comer a las {eatTime}</span>}
            </div>
        </div>
    );
}

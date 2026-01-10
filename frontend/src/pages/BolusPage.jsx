
import React, { useState, useEffect, useRef } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { Button } from '../components/ui/Atoms';
// Hooks
import { useOrphanDetection } from '../hooks/useOrphanDetection';
import { useNutritionDraft } from '../hooks/useNutritionDraft';
import { useBolusCalculator } from '../hooks/useBolusCalculator';

// Components
import { ResultView } from '../components/bolus/ResultView';
import { FoodSmartAutocomplete } from '../components/bolus/FoodSmartAutocomplete';
import { showToast } from '../components/ui/Toast';
// Shared Logic / Store
import { getCalcParams, state } from '../modules/core/store';
import { getCurrentGlucose, getIOBData, getFavorites, getLocalNsConfig } from '../lib/api';

export default function BolusPage() {
    // --- 1. State Management ---
    const [glucose, setGlucose] = useState('');
    const [carbs, setCarbs] = useState('');
    const [carbProfile, setCarbProfile] = useState(null);
    const [foodName, setFoodName] = useState('');
    const [suggestedStrategy, setSuggestedStrategy] = useState(null);
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

    // Toggles
    const [correctionOnly, setCorrectionOnly] = useState(false);
    const [dessertMode, setDessertMode] = useState(false);
    const [dualEnabled, setDualEnabled] = useState(false);
    const [alcoholEnabled, setAlcoholEnabled] = useState(false);
    const [showAdvancedCarbs, setShowAdvancedCarbs] = useState(false);

    // Exercise
    const [exerciseEnabled, setExerciseEnabled] = useState(false);
    const [exerciseIntensity, setExerciseIntensity] = useState('moderate');
    const [exerciseMinutes, setExerciseMinutes] = useState(60);

    // Meta / Learning
    const [plateItems, setPlateItems] = useState([]);
    const [learningHint, setLearningHint] = useState(null);
    const mealMetaRef = useRef(null);

    // Data
    const [iob, setIob] = useState(null);
    const [favorites, setFavorites] = useState([]);
    const [nsConfig] = useState(getLocalNsConfig() || {});

    // --- 2. Custom Hooks ---
    const {
        orphanCarbs, isUsingOrphan, setIsUsingOrphan, checkOrphans
    } = useOrphanDetection();

    const {
        draft, checkDraft, applyDraft, discard: discardDraft
    } = useNutritionDraft();

    const {
        calculate, save, result, setResult, calcUsedParams,
        calculating, saving, confirmRequest, confirmCalculation, cancelConfirmation
    } = useBolusCalculator();

    // --- 3. Effects ---

    const loadData = async () => {
        try {
            const bgData = await getCurrentGlucose(nsConfig);
            if (bgData && bgData.bg_mgdl) setGlucose(String(Math.round(bgData.bg_mgdl)));

            const iobData = await getIOBData(nsConfig);
            if (iobData) setIob(iobData.iob_u ?? iobData.iob_total ?? 0);

            const favs = await getFavorites();
            if (favs) setFavorites(favs);

            await checkDraft();
            await checkOrphans();
        } catch (e) {
            console.warn(e);
        }
    };

    useEffect(() => {
        // Init from State (Legacy/Transitions)
        if (state.tempCarbs) {
            setCarbs(String(state.tempCarbs));
            if (state.tempReason && state.tempReason.startsWith("Fav: ")) {
                setFoodName(state.tempReason.replace("Fav: ", ""));
            }
            state.tempCarbs = null;
            state.tempReason = null;
        }
        if (state.tempLearningHint) {
            setLearningHint(state.tempLearningHint);
            state.tempLearningHint = null;
        }
        if (state.tempItems) {
            setPlateItems(state.tempItems);
        }
        if (state.tempItems || state.tempFat || state.tempProtein) {
            mealMetaRef.current = {
                items: state.tempItems || [],
                fat: state.tempFat || 0,
                protein: state.tempProtein || 0,
                fiber: state.tempFiber || 0
            };
        }
        state.tempFat = null;
        state.tempProtein = null;
        state.tempFiber = null;
        state.tempItems = null;

        loadData();
    }, []); // Check deps? checkDraft/checkOrphans are stable via useCallback? Yes.

    // Strategy Suggestion
    useEffect(() => {
        if (!foodName) {
            setSuggestedStrategy(null);
            return;
        }
        const match = favorites.find(f => f.name.toLowerCase() === foodName.trim().toLowerCase());
        if (match && match.strategy && match.strategy.type === 'dual' && !dualEnabled) {
            setSuggestedStrategy(match.strategy);
        } else {
            setSuggestedStrategy(null);
        }
    }, [foodName, dualEnabled, favorites]);


    // --- 4. Handlers ---

    const handleCalculateClick = (override = {}) => {
        calculate({
            glucose, carbs, slot, correctionOnly, dessertMode, dualEnabled,
            alcoholEnabled, exercise: { planned: exerciseEnabled, minutes: exerciseMinutes, intensity: exerciseIntensity },
            overrideParams: override,
            orphanContext: { isUsing: isUsingOrphan, data: orphanCarbs },
            mealMeta: mealMetaRef.current
        });
    };

    const handleSaveClick = (dose, siteId) => {
        save({
            confirmedDose: dose, siteId,
            carbs, glucose, foodName,
            orphanContext: { isUsing: isUsingOrphan, data: orphanCarbs },
            mealMeta: mealMetaRef.current,
            date, nsConfig, alcoholEnabled,
            plateItems
        });
    };

    // Helper for Orphan Dual Logic
    const getOrphanDualStatus = (oc) => {
        if (!oc || oc._diffMode) return { needed: false, isFat: false };
        const params = getCalcParams();
        const th = params?.warsaw?.trigger_threshold_kcal || 300;
        const kcal = (oc.fat || 0) * 9 + (oc.protein || 0) * 4;
        const isFat = kcal >= th;
        const isCarb = (oc.carbs || 0) >= 50;
        return { needed: isFat || isCarb, isFat };
    };
    const orphanDual = getOrphanDualStatus(orphanCarbs);


    // --- 5. Render ---
    return (
        <>
            <Header title="Calcular Bolo" showBack={true} />
            <main className="page" style={{ paddingBottom: '90px' }}>

                {/* INPUT SECTION */}
                {!result && (
                    <div className="stack fade-in">

                        {/* Nutrition Draft */}
                        {draft && (
                            <div className="fade-in" style={{
                                background: '#f5f3ff', border: '1px solid #8b5cf6',
                                borderRadius: '12px', padding: '1rem', marginBottom: '1rem',
                                display: 'flex', flexDirection: 'column', gap: '8px'
                            }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#5b21b6', fontWeight: 700 }}>
                                    <span>📩 Borrador Recibido</span>
                                    <span style={{ fontSize: '0.75rem', fontWeight: 400, background: 'rgba(0,0,0,0.05)', padding: '2px 8px', borderRadius: '10px' }}>
                                        hace {Math.round((new Date() - new Date(draft.updated_at)) / 60000)} min
                                    </span>
                                </div>
                                <div style={{ fontSize: '0.9rem', color: '#4c1d95' }}>
                                    <div><strong>{draft.carbs}g Carbohidratos</strong></div>
                                    {(draft.fat > 0 || draft.protein > 0) && (
                                        <div style={{ fontSize: '0.85rem' }}>{draft.fat}g Grasas, {draft.protein}g Proteínas</div>
                                    )}
                                    {draft.notes && <div style={{ fontStyle: 'italic', fontSize: '0.8rem', marginTop: '4px' }}>"{draft.notes}"</div>}
                                </div>
                                <div style={{ display: 'flex', gap: '10px', marginTop: '5px' }}>
                                    <Button onClick={() => applyDraft((d) => {
                                        setCarbs(String(d.carbs));
                                        mealMetaRef.current = { items: d.items || [], fat: d.fat, protein: d.protein, fiber: d.fiber };
                                        const kcal = d.fat * 9 + d.protein * 4;
                                        if (kcal > 250) {
                                            setDualEnabled(true);
                                            showToast("💡 Bolo Dual activado por contenido graso.", "info", 4000);
                                        }
                                    })} style={{ background: '#7c3aed', color: '#fff', fontSize: '0.85rem', padding: '6px 12px' }}>
                                        Usar Datos
                                    </Button>
                                    <Button onClick={() => { if (confirm("¿Descartar?")) discardDraft(); }} variant="outline" style={{ fontSize: '0.85rem', padding: '6px 12px', color: '#ef4444', borderColor: '#ef4444' }}>
                                        Descartar
                                    </Button>
                                </div>
                            </div>
                        )}

                        {/* Orphan Alert */}
                        {orphanCarbs && !isUsingOrphan && !draft && (
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
                                    {orphanCarbs._diffMode ? (
                                        <div>
                                            Actualización: <strong>{(orphanCarbs._originalCarbs || 0).toFixed(1)}g Tot</strong>.
                                            Aplicado: <strong>{orphanCarbs._alreadyApplied.toFixed(1)}g</strong>.
                                            <br /><span style={{ fontWeight: 800 }}>Diferencia: +{(orphanCarbs._netCarbs || 0).toFixed(1)}g HC</span>
                                        </div>
                                    ) : (
                                        <>Detectados: <strong>{(orphanCarbs.carbs || 0).toFixed(1)}g HC</strong></>
                                    )}
                                    {orphanDual.needed && (
                                        <div style={{ marginTop: '5px', fontWeight: 600, color: '#15803d' }}>
                                            Starting 💡 {orphanDual.isFat ? 'Grasas altas.' : 'HC altos.'} Se recomienda <strong>Bolo Dual</strong>.
                                        </div>
                                    )}
                                </div>
                                <div style={{ display: 'flex', gap: '10px' }}>
                                    <Button onClick={() => {
                                        const valToSet = orphanCarbs._diffMode ? orphanCarbs._netCarbs : orphanCarbs.carbs;
                                        setCarbs((valToSet || 0).toFixed(1));
                                        setIsUsingOrphan(true);

                                        // CRITICAL FIX: Transfer Orphan Macros to mealMeta for simulation
                                        mealMetaRef.current = {
                                            items: [{ name: "Importado (MFP/Externo)", carbs: valToSet, amount: 1 }],
                                            fat: orphanCarbs.fat || 0,
                                            protein: orphanCarbs.protein || 0,
                                            fiber: orphanCarbs.fiber || 0
                                        };

                                        if (orphanCarbs._diffMode) {
                                            const now = new Date();
                                            setDate(new Date(now.getTime() - (now.getTimezoneOffset() * 60000)).toISOString().slice(0, 16));
                                        }
                                        if (orphanDual.needed) setDualEnabled(true);
                                        showToast("✅ Datos aplicados.", "success");
                                    }} style={{ background: '#22c55e', color: '#fff', fontSize: '0.85rem', padding: '6px 12px' }}>
                                        Usar {orphanCarbs._diffMode ? 'Diferencia' : 'Datos'}
                                    </Button>
                                    <Button onClick={() => setIsUsingOrphan(false)} variant="outline" style={{ fontSize: '0.85rem', padding: '6px 12px' }}>Ignorar</Button>
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
                                    🔗 Vinculado a {parseFloat((orphanCarbs.carbs || 0).toFixed(1))}g externos.
                                </div>
                                <button onClick={() => setIsUsingOrphan(false)} style={{ background: 'none', border: 'none', color: '#3b82f6', fontWeight: 600, fontSize: '0.8rem', cursor: 'pointer' }}>
                                    Desvincular
                                </button>
                            </div>
                        )}

                        {/* Glucose Input */}
                        <div className="form-group">
                            <div className="label-row"><span className="label-text">💧 Glucosa Actual</span></div>
                            <div style={{ position: 'relative' }}>
                                <input type="number" value={glucose} onChange={e => setGlucose(e.target.value)} placeholder="mg/dL" className="text-center big-input" style={{ width: '100%', fontSize: '1.5rem', fontWeight: 800, color: 'var(--primary)', padding: '0.5rem', borderRadius: '8px', border: '1px solid #cbd5e1' }} />
                                <span style={{ position: 'absolute', right: '1rem', top: '1rem', color: 'var(--text-muted)' }}>mg/dL</span>
                            </div>
                        </div>

                        {/* Food Input */}
                        <div className="form-group">
                            <div className="label-row"><span className="label-text">🍽️ ¿Qué vas a comer? (Opcional)</span></div>
                            <FoodSmartAutocomplete
                                value={foodName}
                                onChange={setFoodName}
                                favorites={favorites}
                                onSelect={(item) => {
                                    setFoodName(item.name);
                                    setCarbs(String(item.carbs));
                                    // CRITICAL FIX: Transfer Macros to mealMeta for successful simulation
                                    mealMetaRef.current = {
                                        items: [{ name: item.name, carbs: item.carbs, amount: 1 }],
                                        fat: item.fat || item.fat_g || 0,
                                        protein: item.protein || item.protein_g || 0,
                                        fiber: item.fiber || item.fiber_g || 0
                                    };
                                    // Trigger toast or visual feedback? No need, simulation will update.
                                }}
                            />
                            {suggestedStrategy && (
                                <div className="fade-in" style={{
                                    marginTop: '0.5rem', background: '#eff6ff',
                                    border: '1px dashed #3b82f6', borderRadius: '8px',
                                    padding: '0.8rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between'
                                }}>
                                    <div style={{ fontSize: '0.85rem', color: '#1e3a8a', paddingRight: '10px' }}>
                                        💡 Con <strong>{foodName}</strong> sueles usar <strong>Bolo Dual</strong>.
                                    </div>
                                    <Button onClick={() => { setDualEnabled(true); setSuggestedStrategy(null); }} style={{ fontSize: '0.75rem', padding: '5px 10px', height: 'auto' }}>Aplicar</Button>
                                    <div onClick={() => setSuggestedStrategy(null)} style={{ cursor: 'pointer', marginLeft: '10px', fontSize: '1.2rem' }}>×</div>
                                </div>
                            )}
                        </div>

                        {/* Date */}
                        <div className="form-group">
                            <label style={{ fontSize: '0.85rem', color: '#64748b' }}>Fecha / Hora</label>
                            <input type="datetime-local" value={date} onChange={e => setDate(e.target.value)} style={{ width: '100%', padding: '0.5rem', borderRadius: '8px', border: '1px solid #cbd5e1' }} />
                        </div>

                        {/* Slot/Toggles */}
                        <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'center', margin: '1rem 0' }}>
                            <select value={slot} onChange={e => setSlot(e.target.value)} style={{ padding: '0.5rem', borderRadius: '8px', border: '1px solid #cbd5e1', background: '#fff' }}>
                                <option value="breakfast">Desayuno</option>
                                <option value="lunch">Comida</option>
                                <option value="dinner">Cena</option>
                                <option value="snack">Snack</option>
                            </select>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.9rem' }}>
                                <input type="checkbox" checked={correctionOnly} onChange={e => { setCorrectionOnly(e.target.checked); if (e.target.checked) setCarbs("0"); }} />
                                Solo Corrección
                            </label>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.9rem' }}>
                                <input type="checkbox" checked={dessertMode} onChange={e => { setDessertMode(e.target.checked); if (e.target.checked) setDualEnabled(false); }} />
                                Modo Microbolos
                            </label>
                        </div>

                        {/* Carbs Input */}
                        <div className={`form-group ${correctionOnly ? 'opacity-50 pointer-events-none' : ''}`}>
                            <div className="label-row"><span className="label-text">🍪 Carbohidratos</span></div>
                            <div style={{ position: 'relative' }}>
                                <input type="number" value={carbs} onChange={e => setCarbs(e.target.value)} placeholder="0" className="text-center big-input" style={{ width: '100%', fontSize: '1.5rem', fontWeight: 800, color: 'var(--text)', padding: '0.5rem', borderRadius: '8px', border: '1px solid #cbd5e1' }} />
                                <span style={{ position: 'absolute', right: '1rem', top: '1rem', color: 'var(--text-muted)' }}>g</span>
                            </div>

                            {!correctionOnly && parseFloat(carbs) > 0 && (
                                <div className="fade-in" style={{ marginTop: '10px' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                                        <div style={{ fontSize: '0.85rem', color: '#64748b', fontWeight: 600 }}>
                                            Absorción: <span style={{ color: 'var(--primary)' }}>{carbProfile === 'fast' ? '⚡ Rápida' : (carbProfile === 'slow' ? '🍕 Lenta' : (carbProfile === 'med' ? '🥗 Media' : '🤖 Auto'))}</span>
                                        </div>
                                        <button onClick={() => setShowAdvancedCarbs(!showAdvancedCarbs)} style={{ background: 'none', border: 'none', color: '#3b82f6', fontSize: '0.75rem', fontWeight: 600, cursor: 'pointer', padding: 0 }}>
                                            {showAdvancedCarbs ? 'Ocultar' : 'Ajustar'}
                                        </button>
                                    </div>
                                    {showAdvancedCarbs && (
                                        <div className="stack fade-in" style={{ gap: '8px', padding: '10px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                                            <div style={{ display: 'flex', gap: '8px' }}>
                                                {[{ id: null, label: '🤖 Auto', color: '#6366f1' }, { id: 'fast', label: '⚡ Rápida', color: '#ef4444' }, { id: 'med', label: '🥗 Media', color: '#10b981' }, { id: 'slow', label: '🍕 Lenta', color: '#f59e0b' }].map(p => (
                                                    <button key={p.id} onClick={() => setCarbProfile(p.id)} style={{ flex: 1, padding: '6px', borderRadius: '6px', fontSize: '0.75rem', border: '1px solid', borderColor: carbProfile === p.id ? p.color : '#cbd5e1', background: carbProfile === p.id ? p.color : '#fff', color: carbProfile === p.id ? '#fff' : '#64748b', fontWeight: carbProfile === p.id ? 700 : 400 }}>{p.label}</button>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            )}

                            <div className="carb-presets" style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem', flexWrap: 'wrap', justifyContent: 'center' }}>
                                {[0, 15, 30, 45, 60].map(v => (
                                    <button key={v} onClick={() => setCarbs(String(v))} style={{ padding: '0.3rem 0.8rem', borderRadius: '16px', border: '1px solid #cbd5e1', background: parseFloat(carbs) === v ? 'var(--primary)' : '#fff', color: parseFloat(carbs) === v ? '#fff' : '#334155' }}>
                                        {v}g
                                    </button>
                                ))}
                            </div>
                        </div>

                        {/* Plate Summary */}
                        {plateItems.length > 0 && (
                            <div style={{ marginTop: '-10px', marginBottom: '1rem', padding: '0.8rem', background: '#f8fafc', borderRadius: '12px', border: '1px solid #e2e8f0' }}>
                                <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#64748b', marginBottom: '0.5rem', textTransform: 'uppercase' }}>CONTENIDO DEL PLATO</div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                    {plateItems.map((item, idx) => (
                                        <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', color: '#334155' }}>
                                            <span>{item.amount && item.amount < 10 ? `${item.amount}x` : `•`} {item.name}</span>
                                            <span style={{ fontWeight: 600, color: '#64748b' }}>{item.carbs ? Math.round(item.carbs) : 0}g</span>
                                        </div>
                                    ))}
                                    <div style={{ borderTop: '1px dashed #cbd5e1', paddingTop: '6px', marginTop: '4px', display: 'flex', justifyContent: 'space-between', fontSize: '0.9rem', fontWeight: 800, color: '#1e293b' }}>
                                        <span>Total</span>
                                        <span>{plateItems.reduce((acc, i) => acc + (i.carbs || 0), 0).toFixed(0)}g</span>
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* Learning Hint */}
                        {learningHint && (
                            <div className="fade-in" style={{
                                background: (learningHint.suggest_extended && !dualEnabled) ? '#fff7ed' : (learningHint.suggest_extended ? '#f0fdf4' : '#fff7ed'),
                                border: `1px solid ${(learningHint.suggest_extended && !dualEnabled) ? '#fdba74' : (learningHint.suggest_extended ? '#86efac' : '#fdba74')}`,
                                borderRadius: '12px', padding: '0.8rem', marginBottom: '0.5rem', fontSize: '0.85rem', color: '#334155'
                            }}>
                                <div style={{ fontWeight: 600, color: (learningHint.suggest_extended && !dualEnabled) ? '#c2410c' : (learningHint.suggest_extended ? '#15803d' : '#c2410c'), display: 'flex', alignItems: 'center', gap: '5px', justifyContent: 'space-between' }}>
                                    <span style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>🧠 Memoria de Efectos</span>
                                    {learningHint.suggest_extended && <span style={{ fontSize: '0.75rem', padding: '2px 8px', borderRadius: '12px', background: 'rgba(0,0,0,0.05)' }}>{dualEnabled ? 'Aplicada' : 'Ignorada'}</span>}
                                </div>
                                <div style={{ marginTop: '4px' }}>{learningHint.reason}</div>
                            </div>
                        )}

                        {/* Dual Toggle */}
                        <div className="card" style={{ display: 'flex', justifySelf: 'between', justifyContent: 'space-between', alignItems: 'center', padding: '1rem', border: dualEnabled ? '2px solid #3b82f6' : '1px solid #e2e8f0', background: dualEnabled ? '#eff6ff' : '#fff' }}>
                            <div>
                                <div style={{ fontWeight: 600, color: dualEnabled ? '#1d4ed8' : '#0f172a' }}>🌊 Bolo Dual / Extendido</div>
                                {state.tempFat > 15 && <div style={{ fontSize: '0.75rem', color: '#b91c1c', marginTop: '4px' }}>🔥 Alto en grasas detectado.</div>}
                            </div>
                            <input type="checkbox" checked={dualEnabled} onChange={() => setDualEnabled(!dualEnabled)} style={{ transform: 'scale(1.5)', cursor: 'pointer' }} />
                        </div>

                        {/* Alcohol Toggle */}
                        <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '1rem', border: alcoholEnabled ? '2px solid #8b5cf6' : '1px solid #e2e8f0', background: alcoholEnabled ? '#f5f3ff' : '#fff', marginTop: '0.5rem' }}>
                            <div>
                                <div style={{ fontWeight: 600, color: alcoholEnabled ? '#6d28d9' : '#0f172a' }}>🍷 Alcohol</div>
                                <div style={{ fontSize: '0.8rem', color: '#64748b' }}>Retrasa el pico de glucosa (8h)</div>
                            </div>
                            <input type="checkbox" checked={alcoholEnabled} onChange={() => setAlcoholEnabled(!alcoholEnabled)} style={{ transform: 'scale(1.5)', cursor: 'pointer' }} />
                        </div>

                        {/* Exercise Card */}
                        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '0.8rem', padding: '1rem', border: exerciseEnabled ? '2px solid #10b981' : '1px solid #e2e8f0', background: exerciseEnabled ? '#ecfdf5' : '#fff', marginTop: '1rem' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <div>
                                    <div style={{ fontWeight: 600, color: exerciseEnabled ? '#047857' : '#0f172a' }}>🏃‍♂️ Actividad Física</div>
                                    <div style={{ fontSize: '0.8rem', color: exerciseEnabled ? '#059669' : '#64748b' }}>{exerciseEnabled ? 'Se reducirá el bolo' : 'Ajuste por Ejercicio'}</div>
                                </div>
                                <input type="checkbox" checked={exerciseEnabled} onChange={() => setExerciseEnabled(!exerciseEnabled)} style={{ transform: 'scale(1.5)', cursor: 'pointer' }} />
                            </div>
                            {exerciseEnabled && (
                                <div className="fade-in" style={{ borderTop: '1px dashed #6ee7b7', paddingTop: '0.8rem' }}>
                                    <div style={{ fontSize: '0.85rem', marginBottom: '0.4rem', color: '#065f46' }}>Intensidad</div>
                                    <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
                                        {['low', 'moderate', 'high'].map(lvl => (
                                            <button key={lvl} onClick={() => setExerciseIntensity(lvl)} style={{ flex: 1, padding: '0.4rem', borderRadius: '8px', border: '1px solid', borderColor: exerciseIntensity === lvl ? '#059669' : '#d1fae5', background: exerciseIntensity === lvl ? '#059669' : '#fff', color: exerciseIntensity === lvl ? '#fff' : '#047857', fontSize: '0.85rem', textTransform: 'capitalize' }}>
                                                {lvl === 'low' ? 'Suave' : lvl === 'moderate' ? 'Moderada' : 'Intensa'}
                                            </button>
                                        ))}
                                    </div>
                                    <div style={{ fontSize: '0.85rem', marginBottom: '0.4rem', color: '#065f46' }}>Duración (min)</div>
                                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                        {[30, 60, 90, 120].map(m => (
                                            <button key={m} onClick={() => setExerciseMinutes(m)} style={{ padding: '0.3rem 0.6rem', borderRadius: '8px', border: '1px solid', borderColor: exerciseMinutes === m ? '#059669' : '#d1fae5', background: exerciseMinutes === m ? '#10b981' : '#fff', color: exerciseMinutes === m ? '#fff' : '#047857', fontSize: '0.85rem' }}>{m}</button>
                                        ))}
                                        <input type="number" value={exerciseMinutes} onChange={(e) => setExerciseMinutes(parseInt(e.target.value) || 0)} style={{ width: '60px', padding: '0.3rem', borderRadius: '8px', border: '1px solid #d1fae5', textAlign: 'center' }} />
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

                        <Button onClick={() => handleCalculateClick()} disabled={calculating} className="btn-primary" style={{ width: '100%', padding: '1rem', fontSize: '1.1rem' }}>
                            {calculating ? 'Calculando...' : 'Calcular Bolo'}
                        </Button>
                    </div>
                )}

                {confirmRequest && (
                    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999 }}>
                        <div style={{ background: '#fff', padding: '1.2rem', borderRadius: '12px', maxWidth: '520px', width: '90%', boxShadow: '0 10px 30px rgba(0,0,0,0.2)' }}>
                            <h3 style={{ marginTop: 0, marginBottom: '0.5rem', color: '#b91c1c' }}>Se requiere confirmación</h3>
                            <p style={{ fontSize: '0.95rem', color: '#1f2937' }}>IOB/COB no disponibles o desactualizados. Continuar asumirá IOB=0 y puede causar stacking.</p>
                            <p style={{ fontSize: '0.85rem', color: '#4b5563' }}>Flag: <code>{confirmRequest.requiredFlag}</code></p>
                            <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end', marginTop: '1rem' }}>
                                <Button variant="secondary" onClick={cancelConfirmation}>Cancelar</Button>
                                <Button onClick={confirmCalculation} disabled={calculating}>Continuar</Button>
                            </div>
                        </div>
                    </div>
                )}

                {/* RESULT SECTION */}
                {result && (
                    <ResultView
                        result={result}
                        slot={slot}
                        settings={getCalcParams()}
                        usedParams={calcUsedParams}
                        onBack={() => { setResult(null); }}
                        onSave={handleSaveClick}
                        saving={saving}
                        currentCarbs={carbs}
                        mealMeta={mealMetaRef.current} // Pass macros for simulation
                        foodName={foodName}
                        favorites={favorites}
                        onFavoriteAdded={(newFav) => setFavorites(prev => [...prev, newFav])}
                        alcoholEnabled={alcoholEnabled}
                        carbProfile={carbProfile}
                        nsConfig={nsConfig}
                        onApplyAutosens={(ratio, reason) => {
                            state.autosens = { ratio, reason };
                            handleCalculateClick({ useAutosens: true });
                        }}
                    />
                )}
            </main>
            <BottomNav activeTab="bolus" />
        </>
    );
}

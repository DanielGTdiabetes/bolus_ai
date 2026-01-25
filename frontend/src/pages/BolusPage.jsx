
import React, { useState, useEffect, useRef } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { Button } from '../components/ui/Atoms';
// Hooks
import { useOrphanDetection } from '../hooks/useOrphanDetection';
import { useBolusCalculator } from '../hooks/useBolusCalculator';

// Components
import { ResultView } from '../components/bolus/ResultView';
import { FoodSmartAutocomplete } from '../components/bolus/FoodSmartAutocomplete';
import { showToast } from '../components/ui/Toast';
// Shared Logic / Store
import { getCalcParams, state } from '../modules/core/store';
import { getCurrentGlucose, getIOBData, getFavorites, getLocalNsConfig, fetchRecentNutritionImports } from '../lib/api';

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
    const [autoDualApplied, setAutoDualApplied] = useState(false);
    const [autoDualReason, setAutoDualReason] = useState(null);
    const [alcoholEnabled, setAlcoholEnabled] = useState(false);
    const [showAdvancedCarbs, setShowAdvancedCarbs] = useState(false);

    // Exercise
    const [exerciseEnabled, setExerciseEnabled] = useState(false);
    const [exerciseIntensity, setExerciseIntensity] = useState('moderate');
    const [exerciseMinutes, setExerciseMinutes] = useState(60);
    const [manualEntryEnabled, setManualEntryEnabled] = useState(true);
    const [manualProtein, setManualProtein] = useState('0');
    const [manualFat, setManualFat] = useState('0');
    const [manualFiber, setManualFiber] = useState('0');

    // Meta / Learning
    const [plateItems, setPlateItems] = useState([]);
    const [learningHint, setLearningHint] = useState(null);
    const [visionBolusKind, setVisionBolusKind] = useState(null);
    const [macroHints, setMacroHints] = useState({ fat: 0, protein: 0, fiber: 0, ingestionId: null });
    const mealMetaRef = useRef(null);

    // Data
    const [iob, setIob] = useState(null);
    const [favorites, setFavorites] = useState([]);
    const [nsConfig] = useState(getLocalNsConfig() || {});
    const [importModalOpen, setImportModalOpen] = useState(false);
    const [importLoading, setImportLoading] = useState(false);
    const [importError, setImportError] = useState(null);
    const [recentImports, setRecentImports] = useState([]);
    const [usedImportIds, setUsedImportIds] = useState([]);

    // --- 2. Custom Hooks ---
    const {
        orphanCarbs, isUsingOrphan, setIsUsingOrphan, checkOrphans
    } = useOrphanDetection();


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
        if (state.tempReason === 'restaurant_menu') {
            setDualEnabled(true);
            setAutoDualReason("Modo Restaurante (Bolo Dual sugerido)");
            setAutoDualApplied(true);
        }

        if (state.tempBolusKind) {
            setVisionBolusKind(state.tempBolusKind);
            state.tempBolusKind = null;
        }
        if (state.tempItems) {
            setPlateItems(state.tempItems);
        }
        if (state.tempItems || state.tempFat || state.tempProtein) {
            const meta = {
                items: state.tempItems || [],
                fat: state.tempFat || 0,
                protein: state.tempProtein || 0,
                fiber: state.tempFiber || 0
            };
            mealMetaRef.current = meta;
            setMacroHints({ fat: meta.fat || 0, protein: meta.protein || 0, fiber: meta.fiber || 0, ingestionId: null });
            setManualEntryEnabled(false);
        }
        state.tempFat = null;
        state.tempProtein = null;
        state.tempFiber = null;
        state.tempItems = null;

        loadData();
    }, []); // Check deps? checkOrphans are stable via useCallback? Yes.

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

    const clampMacroValue = (value) => Math.min(300, Math.max(0, value));

    const setMealMeta = (meta) => {
        mealMetaRef.current = meta;
        setMacroHints({
            fat: meta?.fat || 0,
            protein: meta?.protein || 0,
            fiber: meta?.fiber || 0,
            ingestionId: meta?.ingestion_id || null
        });
    };

    const resetMealContext = () => {
        mealMetaRef.current = null;
        setMacroHints({ fat: 0, protein: 0, fiber: 0, ingestionId: null });
        setPlateItems([]);
        setLearningHint(null);
        setVisionBolusKind(null);
        setIsUsingOrphan(false);
        setUsedImportIds([]);
        setImportError(null);
        setAutoDualReason(null);
        setAutoDualApplied(false);
        setResult(null);
        setFoodName('');
        setManualProtein('0');
        setManualFat('0');
        setManualFiber('0');
        state.tempItems = null;
        state.tempFat = null;
        state.tempProtein = null;
        state.tempFiber = null;
        state.tempLearningHint = null;
        state.tempBolusKind = null;
        state.visionResult = null;
        state.visionError = null;
    };

    useEffect(() => {
        const carbsVal = parseFloat(carbs) || 0;
        if (correctionOnly || carbsVal <= 0) {
            setAutoDualReason(null);
            setAutoDualApplied(false);
            return;
        }

        const hasLearningHint = !!learningHint?.suggest_extended;
        const hasMacroTrigger = (macroHints.fat || 0) >= 15 || (macroHints.protein || 0) >= 20;
        const hasVisionTrigger = visionBolusKind === 'extended';

        if ((hasLearningHint || hasMacroTrigger || hasVisionTrigger) && !autoDualApplied) {
            if (!dualEnabled) setDualEnabled(true);
            if (hasLearningHint) {
                setAutoDualReason("Activado automáticamente por memoria de efectos.");
            } else if (hasVisionTrigger) {
                setAutoDualReason("Activado automáticamente por sugerencia de visión IA.");
            } else {
                setAutoDualReason("Activado automáticamente por grasas/proteínas elevadas.");
            }
            setAutoDualApplied(true);
        }
    }, [carbs, correctionOnly, learningHint, macroHints, visionBolusKind, autoDualApplied, dualEnabled]);

    useEffect(() => {
        if (!manualEntryEnabled) return;
        setMealMeta({
            items: [],
            fat: clampMacroValue(parseFloat(manualFat) || 0),
            protein: clampMacroValue(parseFloat(manualProtein) || 0),
            fiber: clampMacroValue(parseFloat(manualFiber) || 0),
            linked_ingestion: false,
            ingestion_id: null
        });
    }, [manualEntryEnabled, manualFat, manualProtein, manualFiber]);

    // --- 4. Handlers ---
    const roundToTenth = (value) => Math.round(value * 10) / 10;
    const handleMacroInput = (setter) => (event) => {
        const { value } = event.target;
        if (value === '') {
            setter('');
            return;
        }
        const parsed = parseFloat(value);
        if (Number.isNaN(parsed)) {
            setter('0');
            return;
        }
        setter(String(clampMacroValue(parsed)));
    };

    const applyImportToMealMeta = (importItem, mode) => {
        const currentMeta = mealMetaRef.current || {};
        const currentItems = currentMeta.items || [];
        const baseMeta = {
            items: currentItems,
            fat: currentMeta.fat || 0,
            protein: currentMeta.protein || 0,
            fiber: currentMeta.fiber || 0,
            linked_ingestion: currentMeta.linked_ingestion || false,
            ingestion_id: currentMeta.ingestion_id || null
        };
        const label = importItem.source ? `Importación (${importItem.source})` : "Importación externa";

        if (mode === 'replace') {
            return {
                items: [{ name: label, carbs: importItem.carbs || 0, amount: 1 }],
                fat: importItem.fat || 0,
                protein: importItem.protein || 0,
                fiber: importItem.fiber || 0,
                linked_ingestion: true,
                ingestion_id: importItem.id || null
            };
        }

        return {
            items: [...baseMeta.items, { name: label, carbs: importItem.carbs || 0, amount: 1 }],
            fat: baseMeta.fat + (importItem.fat || 0),
            protein: baseMeta.protein + (importItem.protein || 0),
            fiber: baseMeta.fiber + (importItem.fiber || 0),
            linked_ingestion: true,
            ingestion_id: baseMeta.ingestion_id || importItem.id || null
        };
    };

    const handleOpenImportModal = async () => {
        setImportModalOpen(true);
        setImportLoading(true);
        setImportError(null);
        try {
            const data = await fetchRecentNutritionImports(10);
            setRecentImports(Array.isArray(data) ? data : []);
        } catch (err) {
            setImportError(err?.message || "No se pudieron cargar importaciones.");
        } finally {
            setImportLoading(false);
        }
    };

    const handleApplyImport = (importItem, mode) => {
        if (mode === 'sum' && usedImportIds.includes(importItem.id)) {
            showToast("⚠️ Ya sumaste esta importación en este cálculo.", "warning");
            return;
        }

        const currentCarbs = parseFloat(carbs) || 0;
        const importCarbs = parseFloat(importItem.carbs) || 0;
        const newCarbs = mode === 'replace' ? importCarbs : currentCarbs + importCarbs;
        setCarbs(String(roundToTenth(newCarbs)));
        setManualEntryEnabled(false);
        setManualFat('0');
        setManualProtein('0');
        setManualFiber('0');
        setMealMeta(applyImportToMealMeta(importItem, mode));
        setIsUsingOrphan(false);

        if (mode === 'sum') {
            setUsedImportIds((prev) => [...prev, importItem.id]);
        }

        setImportModalOpen(false);
        showToast(mode === 'replace' ? "✅ Importación aplicada." : "✅ Importación sumada.", "success");
    };

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

                        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                            <Button
                                variant="secondary"
                                className="text-sm"
                                onClick={handleOpenImportModal}
                            >
                                Cargar importación
                            </Button>
                            <Button
                                variant="outline"
                                className="text-sm"
                                style={{ marginLeft: '0.5rem' }}
                                onClick={() => {
                                    resetMealContext();
                                    setManualEntryEnabled(true);
                                }}
                            >
                                Nueva comida
                            </Button>
                        </div>



                        {/* Orphan Alert */}
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
                                        setManualEntryEnabled(false);
                                        setManualFat('0');
                                        setManualProtein('0');
                                        setManualFiber('0');

                                        // CRITICAL FIX: Transfer Orphan Macros to mealMeta for simulation
                                        setMealMeta({
                                            items: [{ name: "Importado (MFP/Externo)", carbs: valToSet, amount: 1 }],
                                            fat: orphanCarbs.fat || 0,
                                            protein: orphanCarbs.protein || 0,
                                            fiber: orphanCarbs.fiber || 0,
                                            linked_ingestion: true,
                                            ingestion_id: orphanCarbs.id || null
                                        });

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
                                    setManualEntryEnabled(false);
                                    setManualFat('0');
                                    setManualProtein('0');
                                    setManualFiber('0');
                                    // CRITICAL FIX: Transfer Macros to mealMeta for successful simulation
                                    setMealMeta({
                                        items: [{ name: item.name, carbs: item.carbs, amount: 1 }],
                                        fat: item.fat || item.fat_g || 0,
                                        protein: item.protein || item.protein_g || 0,
                                        fiber: item.fiber || item.fiber_g || 0,
                                        linked_ingestion: false,
                                        ingestion_id: null
                                    });
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
                            <select value={slot} onChange={e => { setSlot(e.target.value); resetMealContext(); }} style={{ padding: '0.5rem', borderRadius: '8px', border: '1px solid #cbd5e1', background: '#fff' }}>
                                <option value="breakfast">Desayuno</option>
                                <option value="lunch">Comida</option>
                                <option value="dinner">Cena</option>
                                <option value="snack">Snack</option>
                            </select>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.9rem' }}>
                                <input type="checkbox" checked={correctionOnly} onChange={e => { setCorrectionOnly(e.target.checked); if (e.target.checked) { setCarbs("0"); setDualEnabled(false); setAutoDualReason(null); } }} />
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

                        {/* Manual Macros */}
                        <div className="card" style={{ padding: '1rem', marginTop: '0.5rem', border: manualEntryEnabled ? '2px solid #16a34a' : '1px solid #e2e8f0', background: manualEntryEnabled ? '#f0fdf4' : '#fff' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <div>
                                    <div style={{ fontWeight: 600, color: manualEntryEnabled ? '#166534' : '#0f172a' }}>✍️ Entrada manual</div>
                                    <div style={{ fontSize: '0.75rem', color: manualEntryEnabled ? '#15803d' : '#64748b' }}>Opcional. Solo afecta a pronóstico y avisos.</div>
                                </div>
                                <input
                                    type="checkbox"
                                    checked={manualEntryEnabled}
                                    onChange={() => {
                                        const next = !manualEntryEnabled;
                                        if (next) {
                                            resetMealContext();
                                            setManualProtein('0');
                                            setManualFat('0');
                                            setManualFiber('0');
                                        }
                                        setManualEntryEnabled(next);
                                    }}
                                    style={{ transform: 'scale(1.4)', cursor: 'pointer' }}
                                />
                            </div>
                            {manualEntryEnabled && (
                                <div className="fade-in" style={{ marginTop: '0.8rem', display: 'grid', gap: '0.6rem' }}>
                                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.6rem' }}>
                                        <div>
                                            <label style={{ fontSize: '0.7rem', fontWeight: 700, color: '#475569' }}>Proteínas (g)</label>
                                            <input
                                                type="number"
                                                min="0"
                                                max="300"
                                                value={manualProtein}
                                                onChange={handleMacroInput(setManualProtein)}
                                                onBlur={() => setManualProtein((val) => (val === '' ? '0' : val))}
                                                className="w-full"
                                                style={{ width: '100%', padding: '0.4rem', borderRadius: '8px', border: '1px solid #cbd5e1', textAlign: 'center' }}
                                            />
                                        </div>
                                        <div>
                                            <label style={{ fontSize: '0.7rem', fontWeight: 700, color: '#475569' }}>Fibra (g)</label>
                                            <input
                                                type="number"
                                                min="0"
                                                max="300"
                                                value={manualFiber}
                                                onChange={handleMacroInput(setManualFiber)}
                                                onBlur={() => setManualFiber((val) => (val === '' ? '0' : val))}
                                                className="w-full"
                                                style={{ width: '100%', padding: '0.4rem', borderRadius: '8px', border: '1px solid #cbd5e1', textAlign: 'center' }}
                                            />
                                        </div>
                                        <div>
                                            <label style={{ fontSize: '0.7rem', fontWeight: 700, color: '#475569' }}>Grasas (g)</label>
                                            <input
                                                type="number"
                                                min="0"
                                                max="300"
                                                value={manualFat}
                                                onChange={handleMacroInput(setManualFat)}
                                                onBlur={() => setManualFat((val) => (val === '' ? '0' : val))}
                                                className="w-full"
                                                style={{ width: '100%', padding: '0.4rem', borderRadius: '8px', border: '1px solid #cbd5e1', textAlign: 'center' }}
                                            />
                                        </div>
                                    </div>
                                </div>
                            )}
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
                                {autoDualReason && (
                                    <div style={{ fontSize: '0.75rem', color: '#047857', marginTop: '4px' }}>
                                        ✅ {autoDualReason}
                                    </div>
                                )}
                            </div>
                            <input
                                type="checkbox"
                                checked={dualEnabled}
                                onChange={() => {
                                    const next = !dualEnabled;
                                    setDualEnabled(next);
                                    if (!next) {
                                        setAutoDualReason(null);
                                        setAutoDualApplied(true);
                                    }
                                }}
                                style={{ transform: 'scale(1.5)', cursor: 'pointer' }}
                            />
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

                {importModalOpen && (
                    <div className="draft-modal-backdrop" onClick={() => setImportModalOpen(false)}>
                        <div className="draft-modal" onClick={(e) => e.stopPropagation()}>
                            <div className="draft-modal-header">
                                <h3>Cargar importación</h3>
                                <button className="draft-modal-close" onClick={() => setImportModalOpen(false)}>×</button>
                            </div>
                            <div className="draft-modal-body">
                                {importLoading && <p>Cargando importaciones...</p>}
                                {importError && <p style={{ color: '#b91c1c' }}>{importError}</p>}
                                {!importLoading && !importError && recentImports.length === 0 && (
                                    <p>No hay importaciones recientes pendientes.</p>
                                )}
                                {!importLoading && !importError && recentImports.length > 0 && (
                                    <div className="draft-modal-list" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                                        {recentImports.map((item) => (
                                            <div key={item.id} style={{
                                                border: '1px solid #e2e8f0',
                                                borderRadius: '12px',
                                                padding: '0.75rem',
                                                display: 'flex',
                                                flexDirection: 'column',
                                                gap: '0.5rem'
                                            }}>
                                                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem' }}>
                                                    <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#0f172a' }}>
                                                        {item.source || 'Importación'}
                                                    </div>
                                                    <div style={{ fontSize: '0.75rem', color: '#64748b' }}>
                                                        {new Date(item.timestamp).toLocaleString()}
                                                    </div>
                                                </div>
                                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.5rem', fontSize: '0.8rem' }}>
                                                    <div style={{ background: '#f8fafc', borderRadius: '10px', padding: '0.4rem', textAlign: 'center' }}>
                                                        <div style={{ color: '#64748b' }}>HC</div>
                                                        <strong>{Math.round(item.carbs || 0)}</strong>
                                                    </div>
                                                    <div style={{ background: '#f8fafc', borderRadius: '10px', padding: '0.4rem', textAlign: 'center' }}>
                                                        <div style={{ color: '#64748b' }}>Prot</div>
                                                        <strong>{Math.round(item.protein || 0)}</strong>
                                                    </div>
                                                    <div style={{ background: '#f8fafc', borderRadius: '10px', padding: '0.4rem', textAlign: 'center' }}>
                                                        <div style={{ color: '#64748b' }}>Grasa</div>
                                                        <strong>{Math.round(item.fat || 0)}</strong>
                                                    </div>
                                                    <div style={{ background: '#f8fafc', borderRadius: '10px', padding: '0.4rem', textAlign: 'center' }}>
                                                        <div style={{ color: '#64748b' }}>Fibra</div>
                                                        <strong>{Math.round(item.fiber || 0)}</strong>
                                                    </div>
                                                </div>
                                                <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                                                    <Button
                                                        variant="secondary"
                                                        className="text-xs"
                                                        onClick={() => handleApplyImport(item, 'replace')}
                                                    >
                                                        Reemplazar
                                                    </Button>
                                                    <Button
                                                        className="text-xs"
                                                        onClick={() => handleApplyImport(item, 'sum')}
                                                    >
                                                        Sumar
                                                    </Button>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                )}
            </main>
            <BottomNav activeTab="bolus" />
        </>
    );
}

import React, { useState, useEffect, useMemo } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { Card, Button, Input } from '../components/ui/Atoms';
import {
    getCalcParams, getSplitSettings, state
} from '../modules/core/store';
import { formatTrend } from '../modules/core/utils';
import {
    getCurrentGlucose, calculateBolusWithOptionalSplit,
    saveTreatment, getLocalNsConfig, getIOBData, fetchTreatments,
    getSupplies, updateSupply,
    getFavorites, addFavorite, simulateForecast
} from '../lib/api';
import { showToast } from '../components/ui/Toast';
import { MainGlucoseChart } from '../components/charts/MainGlucoseChart';
import { startRestaurantSession } from '../lib/restaurantApi';
import { navigate } from '../modules/core/router';
import { useStore } from '../hooks/useStore';
import { InjectionSiteSelector, saveInjectionSite, getSiteLabel } from '../components/injection/InjectionSiteSelector';
import { buildHistoryFromSnapshot, shouldDegradeSimulation } from './bolusSimulationUtils';

// Removed local FAV_KEY and helper functions


export default function BolusPage() {
    // State
    const [glucose, setGlucose] = useState('');
    const [carbs, setCarbs] = useState('');
    const [carbProfile, setCarbProfile] = useState(null); // null = Auto, 'fast', 'med', 'slow'
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
    const [showAdvancedCarbs, setShowAdvancedCarbs] = useState(false);
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
    const [calcUsedParams, setCalcUsedParams] = useState(null);
    const [loading, setLoading] = useState(false);
    const [calculating, setCalculating] = useState(false);
    const [saving, setSaving] = useState(false);
    const [confirmRequest, setConfirmRequest] = useState(null);
    const [pendingCalcContext, setPendingCalcContext] = useState(null);

    // Data States
    const [iob, setIob] = useState(null);
    const [nsConfig] = useState(getLocalNsConfig() || {});

    // Nutrition Draft State
    const [draft, setDraft] = useState(null);

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

            // Check for Nutrition Draft (Higher Priority than Orphan)
            try {
                const { getNutritionDraft } = await import('../lib/api');
                const dr = await getNutritionDraft();
                if (dr && dr.active && dr.draft) {
                    setDraft(dr.draft);
                    // If draft exists, we might want to skip orphan check or show both?
                    // Showing both is fine, user chooses.
                }
            } catch (err) {
                console.warn("Draft check failed", err);
            }

            // Recent Treatments (Orphan Carbs Detection)
            try {
                const { fetchTreatments } = await import('../lib/api');
                const treatments = await fetchTreatments({ count: 10 });
                const now = new Date();
                // Find ALL potential orphans in the last 60 mins
                const orphans = treatments.filter(t => {
                    const tDate = new Date(t.created_at);
                    const diffMin = (now.getTime() - tDate.getTime()) / 60000;
                    const hasNutrition = (t.carbs > 0 || t.fat > 0 || t.protein > 0);
                    // Standard orphan check
                    return hasNutrition && (!t.insulin || t.insulin === 0) && diffMin > -5 && diffMin < 60;
                });

                if (orphans.length > 0) {
                    // Sort by "Data Richness" (Carbs + Fat + Protein sum) DESC
                    // This creates a preference for the "fullest" record if duplicates exist
                    orphans.sort((a, b) => {
                        const sumA = (a.carbs || 0) + (a.fat || 0) + (a.protein || 0);
                        const sumB = (b.carbs || 0) + (b.fat || 0) + (b.protein || 0);
                        return sumB - sumA;
                    });

                    // Check if we already applied a partial amount recently?
                    // We look at *Saved Treatments* in the last 90 mins that were marked as "Sincronizado" (orphan usage).
                    const recentSaves = treatments.filter(t => {
                        const tDate = new Date(t.created_at);
                        const diffMin = (now.getTime() - tDate.getTime()) / 60000;
                        // Check notes for "Sincronizado" or look for similarity
                        return diffMin < 90 && t.notes && t.notes.includes("(Sincronizado)");
                    });

                    const bestOrphan = orphans[0];
                    let adjustedOrphan = { ...bestOrphan };
                    let diffCarbs = bestOrphan.carbs;
                    let alreadyApplied = 0;

                    if (recentSaves.length > 0) {
                        // Sum up what we already covered
                        alreadyApplied = recentSaves.reduce((acc, t) => acc + (t.carbs || 0), 0);

                        // If the new total is just an accumulation, offer the difference
                        if (bestOrphan.carbs > alreadyApplied) {
                            diffCarbs = bestOrphan.carbs - alreadyApplied;
                            adjustedOrphan._diffMode = true;
                            adjustedOrphan._originalCarbs = bestOrphan.carbs;
                            adjustedOrphan._alreadyApplied = alreadyApplied;
                            adjustedOrphan._netCarbs = diffCarbs;

                            // Net Macros (Prevent negatives)
                            const alreadyAppliedFat = recentSaves.reduce((acc, t) => acc + (t.fat || 0), 0);
                            const alreadyAppliedProtein = recentSaves.reduce((acc, t) => acc + (t.protein || 0), 0);
                            const alreadyAppliedFiber = recentSaves.reduce((acc, t) => acc + (t.fiber || 0), 0);

                            adjustedOrphan._netFat = Math.max(0, (bestOrphan.fat || 0) - alreadyAppliedFat);
                            adjustedOrphan._netProtein = Math.max(0, (bestOrphan.protein || 0) - alreadyAppliedProtein);
                            adjustedOrphan._netFiber = Math.max(0, (bestOrphan.fiber || 0) - alreadyAppliedFiber);

                        } else if (bestOrphan.carbs <= alreadyApplied + 2) {
                            // Close enough to consider covered
                            adjustedOrphan._fullyCovered = true;
                        }
                    }

                    if (!adjustedOrphan._fullyCovered) {
                        setOrphanCarbs(adjustedOrphan);
                    }
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
                protein: state.tempProtein || 0,
                fiber: state.tempFiber || 0
            };
        }

        // Auto-enable Dual if fat/protein high (UI Heuristic)
        // Removed auto-set to allow user choice based on suggestion
        // if (state.tempFat > 15 || state.tempProtein > 20) {
        //     setDualEnabled(true);
        // }

        state.tempFat = null;
        state.tempProtein = null;
        state.tempFiber = null;
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
                            grams: currentCarbs,
                            carb_profile: carbProfile
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

    const toggleDual = () => {
        const newValue = !dualEnabled;
        setDualEnabled(newValue);
        if (newValue) {
            setDessertMode(false); // Disable Ignore IOB if Dual is enabled
        }
    };

    const applyCalcOutcome = (res, meta = {}) => {
        const { isSick = false, bgVal = null } = meta;
        if (isSick) {
            res.warnings = res.warnings || [];
            res.warnings.push("⚠️ Modo Enfermedad: Dosis aumentada un 20%.");
            if (bgVal > 250) {
                res.warnings.push("🧪 ALERTA: Glucosa alta. Revisa CETONAS.");
            }
        }

        setResult(res);
        const used = res?.calc?.used_params || res?.used_params || res?.calc?.usedParams || res?.usedParams;
        setCalcUsedParams(used || null);

        if (used?.autosens_ratio && used.autosens_ratio !== 1.0) {
            state.autosens = {
                ratio: used.autosens_ratio,
                reason: used.autosens_reason || 'Dynamic TDD'
            };
        }
    };

    const handleConfirmationProceed = async () => {
        if (!pendingCalcContext || !confirmRequest) return;
        setCalculating(true);
        try {
            const { payload, useSplit, splitSettings, meta } = pendingCalcContext;
            const flaggedPayload = { ...payload, [confirmRequest.requiredFlag || "confirm_iob_unknown"]: true };
            const res = await calculateBolusWithOptionalSplit(flaggedPayload, useSplit ? splitSettings : null);
            applyCalcOutcome(res, meta || {});
            setConfirmRequest(null);
        } catch (err) {
            alert("Error: " + (err?.message || "No se pudo confirmar sin IOB."));
        } finally {
            setCalculating(false);
        }
    };

    const handleConfirmationCancel = () => setConfirmRequest(null);

    const handleCalculate = async (overrideParams = null) => {
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

            // Determine Fat and Protein for Warsaw Calculation
            let fatVal = 0;
            let proteinVal = 0;
            if (isUsingOrphan && orphanCarbs) {
                // SAFETY: Use Net values if in Diff Mode to avoid double counting fat/protein in Warsaw calculation
                if (orphanCarbs._diffMode) {
                    fatVal = orphanCarbs._netFat || 0;
                    proteinVal = orphanCarbs._netProtein || 0;
                } else {
                    fatVal = orphanCarbs.fat || 0;
                    proteinVal = orphanCarbs.protein || 0;
                }
            } else if (mealMetaRef.current) {
                fatVal = mealMetaRef.current.fat || 0;
                proteinVal = mealMetaRef.current.protein || 0;
            }
            // Add tempFat/Protein from state if not found (legacy fallback for first navigation)
            if (fatVal === 0 && proteinVal === 0) {
                if (state.tempFat) fatVal = state.tempFat;
                if (state.tempProtein) proteinVal = state.tempProtein;
            }

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
                fat_g: correctionOnly ? 0 : fatVal,
                protein_g: correctionOnly ? 0 : proteinVal,
                fiber_g: (correctionOnly || !mealMetaRef.current) ? 0 : (mealMetaRef.current.fiber || 0),
                bg_mgdl: isNaN(bgVal) ? null : bgVal,
                meal_slot: slot,
                target_mgdl: slotParams.target,
                cr_g_per_u: finalIcr,
                isf_mgdl_per_u: finalIsf,
                dia_hours: mealParams.dia_hours || 4.0,
                round_step_u: mealParams.round_step_u || 0.5,
                max_bolus_u: mealParams.max_bolus_u || 15,
                warsaw_safety_factor: mealParams.warsaw?.safety_factor,
                warsaw_safety_factor_dual: mealParams.warsaw?.safety_factor_dual,
                warsaw_trigger_threshold_kcal: mealParams.warsaw?.trigger_threshold_kcal,
                ignore_iob: dessertMode,
                alcohol: alcoholEnabled,
                exercise: {
                    planned: exerciseEnabled,
                    minutes: exerciseEnabled ? (parseInt(exerciseMinutes) || 0) : 0,
                    intensity: exerciseIntensity
                },
                // Pass Autosens Data explicitly if available
                autosens_ratio: (overrideParams?.useAutosens ? (state.autosens?.ratio || 1.0) : 1.0),
                autosens_reason: state.autosens?.reason || null
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
            setPendingCalcContext({ payload, useSplit, splitSettings: useSplit ? splitSettings : null, meta: { isSick, bgVal } });
            const res = await calculateBolusWithOptionalSplit(payload, useSplit ? splitSettings : null);

            applyCalcOutcome(res, { isSick, bgVal });
        } catch (e) {
            const code = e?.error_code || e?.payload?.error_code;
            if (code && String(code).includes("CONFIRM_REQUIRED")) {
                setConfirmRequest({
                    code,
                    requiredFlag: e?.payload?.required_flag || (code.includes("STALE") ? "confirm_iob_stale" : "confirm_iob_unknown"),
                    detail: e?.payload || {}
                });
            } else {
                alert("Error: " + e.message);
            }
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

            // Check for Fiber Deduction in Explanation (Transparency)
            let fiberNote = "";
            const explainList = result.explain || result.calc?.explain;
            if (explainList) {
                const fiberLine = explainList.find(l => l.includes('Fibra') || l.includes('Restando'));
                if (fiberLine) {
                    fiberNote = ` [${fiberLine}]`;
                }
            }

            const treatment = {
                eventType: "Meal Bolus",
                created_at: customDate.toISOString(),
                carbs: (parseFloat(carbs) || 0),
                fat: isUsingOrphan ? (orphanCarbs._diffMode ? (orphanCarbs._netFat || 0) : (orphanCarbs.fat || 0)) : (mealMetaRef.current?.fat || 0),
                protein: isUsingOrphan ? (orphanCarbs._diffMode ? (orphanCarbs._netProtein || 0) : (orphanCarbs.protein || 0)) : (mealMetaRef.current?.protein || 0),
                fiber: isUsingOrphan ? (orphanCarbs._diffMode ? (orphanCarbs._netFiber || 0) : (orphanCarbs.fiber || 0)) : (mealMetaRef.current?.fiber || 0),
                insulin: finalInsulin,
                enteredBy: state.user?.username || "BolusAI",
                notes: `BolusAI: ${(result.kind === 'dual' || result.kind === 'extended') ? 'Dual' : 'Normal'}. Gr: ${carbs}${isUsingOrphan ? ' (Sincronizado)' : ''}. BG: ${glucose}. ${foodName ? 'Comida: ' + foodName + '.' : ''} ${alcoholEnabled ? 'Alcohol Detected.' : ''} ${plateItems.length > 0 ? 'Items: ' + plateItems.map(i => i.name).join(', ') : ''}${fiberNote}`,
                nightscout: {
                    url: nsConfig.url || null,
                },
                injection_site: siteId || null
            };

            // Add Meal Meta for Learning (CRITICAL for Labs/Shadow Mode)
            // We use the Ref if it exists (high fidelity from Vision/Scale), otherwise we construct from UI state.
            const metaItems = (mealMetaRef.current?.items?.length > 0)
                ? mealMetaRef.current.items
                : (plateItems.length > 0 ? plateItems.map(i => i.name) : (foodName ? [foodName] : []));

            const metaFat = mealMetaRef.current?.fat || (plateItems.reduce((acc, i) => acc + (i.fat || 0), 0)) || 0;
            const metaProtein = mealMetaRef.current?.protein || (plateItems.reduce((acc, i) => acc + (i.protein || 0), 0)) || 0;
            const metaFiber = mealMetaRef.current?.fiber || (plateItems.reduce((acc, i) => acc + (i.fiber || 0), 0)) || 0;

            // Only attach meta if there's something to learn from (food exists)
            if (metaItems.length > 0 || parseFloat(carbs) > 0) {
                // If dual, we capture strategy
                const strategy = (result.kind === 'dual' || result.kind === 'extended') ? {
                    kind: 'dual',
                    total: result.total_u_final,
                    upfront: result.upfront_u,
                    later: result.later_u,
                    delay: result.duration_min
                } : { kind: 'normal', total: result.total_u_final };

                treatment.meal_meta = {
                    items: metaItems,
                    fat: metaFat,
                    protein: metaProtein,
                    fiber: metaFiber,
                    strategy
                };
            }

            if (result.kind === 'dual' || result.kind === 'extended') {
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

    // Helper for Orphan Dual Logic (Uses Warsaw Threshold)
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

    return (
        <>
            <Header title="Calcular Bolo" showBack={true} />
            <main className="page" style={{ paddingBottom: '90px' }}>

                {/* INPUT SECTION */}
                {!result && (
                    <div className="stack fade-in">

                        {/* Nutrition Draft Alert */}
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
                                    <div>
                                        <strong>{draft.carbs}g Carbohidratos</strong>
                                    </div>
                                    {(draft.fat > 0 || draft.protein > 0) && (
                                        <div style={{ fontSize: '0.85rem' }}>
                                            {draft.fat}g Grasas, {draft.protein}g Proteínas
                                        </div>
                                    )}
                                    {draft.notes && <div style={{ fontStyle: 'italic', fontSize: '0.8rem', marginTop: '4px' }}>"{draft.notes}"</div>}
                                </div>
                                <div style={{ display: 'flex', gap: '10px', marginTop: '5px' }}>
                                    <Button
                                        onClick={async () => {
                                            setCarbs(String(draft.carbs));

                                            // Set macros in ref for calculation
                                            mealMetaRef.current = {
                                                items: draft.items || [],
                                                fat: draft.fat,
                                                protein: draft.protein,
                                                fiber: draft.fiber
                                            };

                                            // Close draft in backend
                                            try {
                                                const { closeNutritionDraft } = await import('../lib/api');
                                                await closeNutritionDraft();
                                                showToast("✅ Borrador aplicado.", "success");
                                                setDraft(null); // Clear from UI
                                            } catch (e) {
                                                console.error(e);
                                                showToast("Aplicado localmente (error cerrando en servidor)", "warning");
                                            }

                                            // Auto-suggest Dual if heavy meal
                                            const kcal = draft.fat * 9 + draft.protein * 4;
                                            if (kcal > 250) {
                                                setDualEnabled(true);
                                                showToast("💡 Bolo Dual activado por contenido graso.", "info", 4000);
                                            }
                                        }}
                                        style={{ background: '#7c3aed', color: '#fff', fontSize: '0.85rem', padding: '6px 12px' }}
                                    >
                                        Usar Datos
                                    </Button>
                                    <Button
                                        onClick={async () => {
                                            if (!confirm("¿Descartar este borrador?")) return;
                                            try {
                                                const { discardNutritionDraft } = await import('../lib/api');
                                                await discardNutritionDraft();
                                                setDraft(null);
                                            } catch (e) {
                                                console.error(e);
                                            }
                                        }}
                                        variant="outline"
                                        style={{ fontSize: '0.85rem', padding: '6px 12px', color: '#ef4444', borderColor: '#ef4444' }}
                                    >
                                        Descartar
                                    </Button>
                                </div>
                            </div>
                        )}

                        {/* Orphan Carbs Alert */}
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
                                            Nueva actualización: <strong>{(orphanCarbs._originalCarbs || 0).toFixed(1)}g Total</strong>.
                                            <br />
                                            <span style={{ fontSize: '0.85rem' }}>Ya aplicaste: <strong>{orphanCarbs._alreadyApplied.toFixed(1)}g</strong>.</span>
                                            <br />
                                            <span style={{ fontWeight: 800 }}>Diferencia a cubrir: +{(orphanCarbs._netCarbs || 0).toFixed(1)}g HC</span>
                                        </div>
                                    ) : (
                                        <>
                                            Se han detectado datos externos: <strong>{(orphanCarbs.carbs || 0).toFixed(1)}g HC</strong>
                                            {(orphanCarbs.fat > 0 || orphanCarbs.protein > 0) && (
                                                <span>, {(orphanCarbs.fat || 0).toFixed(1)}g Grasas, {(orphanCarbs.protein || 0).toFixed(1)}g Prot.</span>
                                            )}
                                        </>
                                    )}

                                    {orphanDual.needed && (
                                        <div style={{ marginTop: '5px', fontWeight: 600, color: '#15803d' }}>
                                            💡 {orphanDual.isFat ? 'Muchas grasas detectadas.' : 'Cantidad alta detectada.'} Se recomienda <strong>Bolo Dual</strong>.
                                        </div>
                                    )}
                                </div>
                                <div style={{ display: 'flex', gap: '10px' }}>
                                    <Button
                                        onClick={() => {
                                            const valToSet = orphanCarbs._diffMode ? orphanCarbs._netCarbs : orphanCarbs.carbs;

                                            // Format to 1 decimal for input
                                            setCarbs((valToSet || 0).toFixed(1));
                                            setIsUsingOrphan(true);

                                            // IMPORTANT: If we are applying a DIFFERENCE (new food added now), 
                                            // we must reset the time to NOW, otherwise it might use the old meal time.
                                            if (orphanCarbs._diffMode) {
                                                const now = new Date();
                                                const localIso = new Date(now.getTime() - (now.getTimezoneOffset() * 60000)).toISOString().slice(0, 16);
                                                setDate(localIso);
                                            }

                                            const totalC = orphanCarbs._diffMode ? orphanCarbs._originalCarbs : orphanCarbs.carbs;
                                            // Use logic calculated at render to ensure consistency with UI
                                            const needsDual = orphanDual.needed;

                                            if (needsDual) {
                                                setDualEnabled(true);
                                                showToast("✅ Datos aplicados y Bolo Dual activado por grasas/HC.", "success");
                                            } else {
                                                showToast("✅ Usando datos sincronizados.", "success");
                                            }
                                        }}
                                        style={{ background: '#22c55e', color: '#fff', fontSize: '0.85rem', padding: '6px 12px' }}
                                    >
                                        Usar {orphanCarbs._diffMode ? 'Diferencia (+' + Math.round(orphanCarbs._netCarbs) + 'g)' : 'Datos'}
                                        {orphanDual.needed ? ' + Dual' : ''}
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
                                    🔗 Vinculado a {parseFloat((orphanCarbs.carbs || 0).toFixed(1))}g externos. No se duplicarán.
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
                                    }
                                }} />
                                Solo Corrección
                            </label>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.9rem' }}>
                                <input type="checkbox" checked={dessertMode} onChange={e => {
                                    const val = e.target.checked;
                                    setDessertMode(val);
                                    if (val) {
                                        setDualEnabled(false); // Disable Dual if Ignore IOB is enabled
                                    }
                                }} />
                                Modo Microbolos
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

                            {/* Carb Profile Info / Auto Selector */}
                            {!correctionOnly && parseFloat(carbs) > 0 && (
                                <div className="fade-in" style={{ marginTop: '10px' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                                        <div style={{ fontSize: '0.85rem', color: '#64748b', fontWeight: 600 }}>
                                            Absorción: <span style={{ color: 'var(--primary)' }}>
                                                {carbProfile === 'fast' ? '⚡ Rápida' : (carbProfile === 'slow' ? '🍕 Lenta' : (carbProfile === 'med' ? '🥗 Media' : '🤖 Auto'))}
                                            </span>
                                        </div>
                                        <button
                                            onClick={() => setShowAdvancedCarbs(!showAdvancedCarbs)}
                                            style={{ background: 'none', border: 'none', color: '#3b82f6', fontSize: '0.75rem', fontWeight: 600, cursor: 'pointer', padding: 0 }}
                                        >
                                            {showAdvancedCarbs ? 'Ocultar' : 'Ajustar'}
                                        </button>
                                    </div>

                                    {showAdvancedCarbs && (
                                        <div className="stack fade-in" style={{ gap: '8px', padding: '10px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                                            <div style={{ display: 'flex', gap: '8px' }}>
                                                {[
                                                    { id: null, label: '🤖 Auto', color: '#6366f1' },
                                                    { id: 'fast', label: '⚡ Rápida', color: '#ef4444' },
                                                    { id: 'med', label: '🥗 Media', color: '#10b981' },
                                                    { id: 'slow', label: '🍕 Lenta', color: '#f59e0b' }
                                                ].map(p => (
                                                    <button
                                                        key={p.id}
                                                        onClick={() => setCarbProfile(p.id)}
                                                        style={{
                                                            flex: 1, padding: '6px', borderRadius: '6px', fontSize: '0.75rem',
                                                            border: '1px solid',
                                                            borderColor: carbProfile === p.id ? p.color : '#cbd5e1',
                                                            background: carbProfile === p.id ? p.color : '#fff',
                                                            color: carbProfile === p.id ? '#fff' : '#64748b',
                                                            fontWeight: carbProfile === p.id ? 700 : 400,
                                                            transition: 'all 0.2s'
                                                        }}
                                                    >
                                                        {p.label}
                                                    </button>
                                                ))}
                                            </div>
                                            <p style={{ fontSize: '0.7rem', color: '#94a3b8', margin: 0, textAlign: 'center' }}>
                                                El modo Auto decide la curva según macros e inulina.
                                            </p>
                                        </div>
                                    )}
                                </div>
                            )}

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

                {confirmRequest && (
                    <div style={{
                        position: 'fixed',
                        inset: 0,
                        background: 'rgba(0,0,0,0.45)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        zIndex: 9999
                    }}>
                        <div style={{ background: '#fff', padding: '1.2rem', borderRadius: '12px', maxWidth: '520px', width: '90%', boxShadow: '0 10px 30px rgba(0,0,0,0.2)' }}>
                            <h3 style={{ marginTop: 0, marginBottom: '0.5rem', color: '#b91c1c' }}>Se requiere confirmación</h3>
                            <p style={{ fontSize: '0.95rem', color: '#1f2937' }}>
                                IOB/COB no disponibles o desactualizados. Continuar asumirá IOB=0 y puede causar stacking o hipoglucemias.
                            </p>
                            <p style={{ fontSize: '0.85rem', color: '#4b5563' }}>
                                Estado: {confirmRequest.code} · Flag: <code>{confirmRequest.requiredFlag}</code>
                            </p>
                            <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end', marginTop: '1rem' }}>
                                <Button variant="secondary" onClick={handleConfirmationCancel}>Cancelar / Modo manual</Button>
                                <Button onClick={handleConfirmationProceed} disabled={calculating}>Continuar (confirmar)</Button>
                            </div>
                        </div>
                    </div>
                )}


                {/* RESULT SECTION */}
                {result && (
                    <ResultView
                        result={result}
                        slot={slot} // Pass slot for fallback
                        usedParams={calcUsedParams}
                        onBack={() => {
                            setResult(null);
                            setCalcUsedParams(null);
                        }}
                        onSave={handleSave}
                        saving={saving}
                        currentCarbs={carbs}
                        foodName={foodName}
                        favorites={favorites} // Pass favorites for checking existence
                        onFavoriteAdded={(newFav) => setFavorites(prev => [...prev, newFav])} // Optimistic update or reload
                        alcoholEnabled={alcoholEnabled}
                        carbProfile={carbProfile}
                        nsConfig={nsConfig}
                        onApplyAutosens={(ratio, reason) => {
                            import('../modules/core/store').then(({ state }) => {
                                state.autosens = { ratio, reason };
                                handleCalculate({ useAutosens: true });
                            });
                        }}
                    />
                )}

            </main>
            <BottomNav activeTab="bolus" />
        </>
    );
}

function ResultView({ result, slot, usedParams, onBack, onSave, saving, currentCarbs, foodName, favorites, onFavoriteAdded, alcoholEnabled, onApplyAutosens, carbProfile, nsConfig }) {
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

    // Extract Autosens Suggestion if present
    const autosensLine = (result.explain || result.calc?.explain)?.find(l => l.includes('Autosens (Consejo)'));
    let suggestedRatio = null;
    let suggestedMsg = null;

    if (autosensLine) {
        // Regex to find "Factor 1.09" or similar
        const match = autosensLine.match(/Factor\s+(\d+(\.\d+)?)/);
        if (match) {
            suggestedRatio = parseFloat(match[1]);
            suggestedMsg = autosensLine;
        }
    }

    // ... (rest of logic) ...


    const [predictionData, setPredictionData] = useState(null);
    const [simulating, setSimulating] = useState(false);
    const resolvedParams = useMemo(
        () => usedParams || result?.calc?.used_params || result?.used_params || result?.usedParams,
        [usedParams, result]
    );
    const later = parseFloat(result.later_u || 0);
    const upfront = parseFloat(finalDose || 0);
    const total = upfront + later;

    // Auto-Simulation Debounced
    useEffect(() => {
        if (!resolvedParams) return;
        const timer = setTimeout(() => {
            const dose = parseFloat(finalDose);
            if (!isNaN(dose) && dose >= 0) {
                runSimulation(dose, later, parseFloat(currentCarbs));
            }
        }, 800);
        return () => clearTimeout(timer);
    }, [finalDose, resolvedParams, currentCarbs, later]);

    const runSimulation = async (doseNow, doseLater, carbsVal) => {
        setSimulating(true);
        setPredictionData(null);
        try {
            const params = resolvedParams;
            if (!params) throw new Error("Parámetros de cálculo no disponibles.");

            const isf = params.isf_mgdl_per_u ?? params.isfMgdlPerU ?? params.isf;
            const icr = params.cr_g_per_u ?? params.crGPerU ?? params.icr;
            const dia = params.dia_hours ?? params.diaHours;
            const peak = params.insulin_peak_minutes ?? params.insulinPeakMinutes ?? (params.insulin_model === 'fiasp' ? 55 : 75);
            const insulinModel = params.insulin_model || 'linear';
            const targetMgdl = params.target_mgdl ?? params.target;

            if ([isf, icr, dia].some(v => v === undefined || v === null)) {
                throw new Error("Parámetros incompletos para simular (ICR/ISF/DIA).");
            }

            // Get glucose from result (calculated context) OR target if missing
            let bgVal = result.glucose?.mgdl;
            if (!bgVal || bgVal <= 0) {
                if (targetMgdl) {
                    bgVal = targetMgdl;
                } else {
                    throw new Error("No hay glucosa ni objetivo para simular.");
                }
            }

            console.info("Simulación con parámetros calculados:", { isf, icr, dia_hours: dia, insulin_model: insulinModel, targetMgdl });

            // Build events
            const boluses = [];

            // Immediate
            const nowU = isNaN(doseNow) ? 0 : doseNow;
            if (nowU > 0) boluses.push({ time_offset_min: 0, units: nowU });

            // Extended (Square wave)
            const extU = isNaN(doseLater) ? 0 : doseLater;
            if (extU > 0) {
                // We send it as a bolus with duration. 
                // Backend ForecastEngine handles this by splitting it into 5-min chunks.
                boluses.push({
                    time_offset_min: 0,
                    units: extU,
                    duration_minutes: result.duration_min || 120
                });
            }

            // This is the most critical check.

            const carbsVal = parseFloat(currentCarbs) || 0;
            const primaryCarbs = carbsVal > 0 ? [{
                time_offset_min: 0,
                grams: carbsVal,
                carb_profile: carbProfile,
                is_dessert: dessertMode
            }] : [];

            let historyEvents = { boluses: [], carbs: [] };
            try {
                const [iobSnapshot, treatments] = await Promise.all([
                    getIOBData(nsConfig),
                    fetchTreatments({ count: 30 })
                ]);
                const iobStatus = iobSnapshot?.iob_info?.status;
                const cobStatus = iobSnapshot?.cob_info?.status || iobSnapshot?.cob_status;
                if (shouldDegradeSimulation(iobStatus, cobStatus)) {
                    setPredictionData({
                        quality: "low",
                        warnings: ["Pronóstico incompleto: falta IOB/COB (requiere confirmación)"],
                        series: []
                    });
                    return;
                }
                historyEvents = buildHistoryFromSnapshot(iobSnapshot, treatments, new Date());
            } catch (ctxErr) {
                console.warn("Context fetch for simulation failed", ctxErr);
            }

            const events = {
                boluses: [...historyEvents.boluses, ...boluses],
                carbs: [...historyEvents.carbs, ...primaryCarbs]
            };

            const payload = {
                start_bg: bgVal,
                horizon_minutes: 300, // Reduced slightly to focus on relevant action time
                params: {
                    isf: isf,
                    icr: icr,
                    dia_minutes: dia * 60,
                    insulin_peak_minutes: peak,
                    carb_absorption_minutes: 150, // TUNED: Faster absorption (2.5h) to match Fiasp/Novo better and avoid fake dips
                    insulin_model: insulinModel
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

                {resolvedParams && (
                    <div style={{
                        display: 'inline-flex',
                        gap: '8px',
                        alignItems: 'center',
                        background: '#eef2ff',
                        color: '#312e81',
                        padding: '8px 12px',
                        borderRadius: '12px',
                        border: '1px solid #c7d2fe',
                        margin: '0.5rem 0'
                    }}>
                        <span style={{ fontWeight: 700 }}>⚙️ Parámetros usados</span>
                        <span style={{ fontSize: '0.85rem' }}>
                            ICR {resolvedParams.cr_g_per_u}g/U · ISF {resolvedParams.isf_mgdl_per_u} mg/dL/U · DIA {resolvedParams.dia_hours}h · Modelo {resolvedParams.insulin_model || 'linear'}
                        </span>
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


                {(predictionData || simulating) && (
                    <div className="fade-in" style={{
                        padding: '1rem',
                        marginBottom: '1.5rem',
                        borderRadius: '16px',
                        background: '#f8fafc',
                        border: '1px solid #e2e8f0',
                        display: 'flex', flexDirection: 'column', transition: 'all 0.3s ease'
                    }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1rem' }}>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                <span style={{ fontSize: '0.85rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>
                                    Pronóstico Metabólico {predictionData.slow_absorption_active ? '🐢' : ''}
                                </span>
                                {!simulating && predictionData?.absorption_profile_used && (
                                    <div style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'flex', gap: '6px', alignItems: 'center' }}>
                                        <span style={{ fontWeight: 600 }}>
                                            {predictionData.absorption_profile_used === 'fast' ? '⚡ Rápida' :
                                                predictionData.absorption_profile_used === 'slow' ? '🍕 Lenta' :
                                                    predictionData.absorption_profile_used === 'med' ? '🥗 Media' : '⚪ Sin carbs'}
                                        </span>
                                        <span style={{
                                            padding: '1px 5px', borderRadius: '4px', fontSize: '0.65rem', fontWeight: 800,
                                            background: predictionData.absorption_confidence === 'high' ? '#dcfce7' : (predictionData.absorption_confidence === 'medium' ? '#fef9c3' : '#fee2e2'),
                                            color: predictionData.absorption_confidence === 'high' ? '#166534' : (predictionData.absorption_confidence === 'medium' ? '#854d0e' : '#991b1b')
                                        }}>
                                            Confianza {predictionData.absorption_confidence === 'high' ? 'Alta' : (predictionData.absorption_confidence === 'medium' ? 'Media' : 'Baja')}
                                        </span>
                                    </div>
                                )}
                            </div>
                            <div style={{ textAlign: 'right' }}>
                                {simulating ? (
                                    <div style={{ fontSize: '0.8rem', color: '#64748b', fontStyle: 'italic' }}>Calculando...</div>
                                ) : (
                                    <>
                                        <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#1e293b' }}>
                                            {Math.round(predictionData.summary.ending_bg)}<span style={{ fontSize: '0.7rem', color: '#64748b', marginLeft: '2px' }}>mg/dL</span>
                                        </div>
                                        <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>En 4 horas</div>
                                    </>
                                )}
                            </div>
                        </div>

                        {/* Chart Area */}
                        <div style={{ height: '160px', width: '100%', position: 'relative', marginBottom: '1rem' }}>
                            {simulating ? (
                                <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                    <div className="pulse-animation" style={{ width: '40px', height: '40px', borderRadius: '50%', background: '#e2e8f0' }}></div>
                                </div>
                            ) : (
                                <MainGlucoseChart
                                    predictionData={predictionData}
                                    height={160}
                                    hideLegend
                                    syncId="bolus-preview"
                                    showTargetBand
                                    targetLow={resolvedParams.target - 20}
                                    targetHigh={resolvedParams.target + 20}
                                />
                            )}
                        </div>

                        {/* Indicators Row */}
                        {!simulating && predictionData && (
                            <div style={{ display: 'flex', justifyContent: 'space-around', alignItems: 'center', width: '100%', borderTop: '1px solid #e2e8f0', paddingTop: '10px' }}>
                                <div style={{ textAlign: "center" }}>
                                    <div style={{ fontSize: "0.65rem", color: "#64748b", textTransform: 'uppercase' }}>Mínimo</div>
                                    <div style={{ fontSize: "1rem", fontWeight: 800, color: predictionData.summary.min_bg < 70 ? '#dc2626' : '#166534' }}>
                                        {Math.round(predictionData.summary.min_bg)}
                                    </div>
                                </div>
                                <div style={{ height: '20px', width: '1px', background: '#cbd5e1' }}></div>
                                <div style={{ textAlign: "center" }}>
                                    <div style={{ fontSize: "0.65rem", color: "#64748b", textTransform: 'uppercase' }}>Máximo</div>
                                    <div style={{ fontSize: "1rem", fontWeight: 800, color: "#1e293b" }}>
                                        {Math.round(predictionData.summary.max_bg)}
                                    </div>
                                </div>
                                <div style={{ height: '20px', width: '1px', background: '#cbd5e1' }}></div>
                                <div style={{ textAlign: "center" }}>
                                    <div style={{ fontSize: "0.65rem", color: "#64748b", textTransform: 'uppercase' }}>Pico en</div>
                                    <div style={{ fontSize: "1rem", fontWeight: 800, color: "#1e293b" }}>
                                        {predictionData.summary.time_to_min}m
                                    </div>
                                </div>
                            </div>
                        )}
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
            {(result.explain || result.calc?.explain)?.filter(l => l.includes('⛔') || l.includes('⚠️')).map((line, i) => (
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
                {(result.explain || result.calc?.explain)?.filter(l => !l.includes('⛔') && !l.includes('⚠️')).map((line, i) => <li key={i}>{line}</li>)}
            </ul>

            {result.warnings && result.warnings.length > 0 && (
                <div style={{ background: '#fff7ed', color: '#c2410c', padding: '0.8rem', margin: '1rem 0', borderRadius: '8px', fontSize: '0.85rem', border: '1px solid #fed7aa' }}>
                    <strong>⚠️ Atención:</strong>
                    {result.warnings.map((w, i) => <div key={i}>• {w}</div>)}
                </div>
            )}

            {/* Autosens Suggestion Alert */}
            {autosensLine && suggestedRatio && (
                <div style={{ background: '#eff6ff', color: '#1e40af', padding: '0.8rem', margin: '1rem 0', borderRadius: '8px', fontSize: '0.85rem', border: '1px solid #bfdbfe' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                        <strong>💡 Sugerencia Autosens:</strong>
                        <button onClick={() => {
                            if (onApplyAutosens) onApplyAutosens(suggestedRatio, suggestedMsg);
                        }} style={{
                            background: '#2563eb', color: 'white', border: 'none', borderRadius: '6px',
                            padding: '4px 10px', fontSize: '0.75rem', fontWeight: 'bold', cursor: 'pointer'
                        }}>
                            Aplicar
                        </button>
                    </div>
                    {/* Render the extracted explanation cleanly */}
                    {(result.explain || result.calc?.explain).filter(l => l.includes('Autosens') || l.includes('NO APLICADO')).map((l, i) => (
                        <div key={i} style={{ marginLeft: '10px', marginBottom: '4px' }}>{l.replace('🔍', '').replace('⚠️', '')}</div>
                    ))}
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
                    autoSelect={true}
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

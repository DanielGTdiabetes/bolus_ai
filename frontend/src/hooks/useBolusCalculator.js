
import { useState } from 'react';
import {
    calculateBolusWithOptionalSplit,
    saveTreatment,
    getSupplies,
    updateSupply,
    saveInjectionSite,
    getSiteLabel,
    saveActivePlan
} from '../lib/api';
import {
    getCalcParams,
    getSplitSettings,
    state,
    saveDualPlan
} from '../modules/core/store';
import { startRestaurantSession } from '../lib/restaurantApi';
import { navigate } from '../modules/core/navigation';
import { showToast } from '../components/ui/Toast';

export function useBolusCalculator() {
    const [result, setResult] = useState(null);
    const [calcUsedParams, setCalcUsedParams] = useState(null);
    const [calculating, setCalculating] = useState(false);
    const [saving, setSaving] = useState(false);
    const [confirmRequest, setConfirmRequest] = useState(null);
    const [pendingCalcContext, setPendingCalcContext] = useState(null);

    const applyCalcOutcome = (res, meta = {}) => {
        const { isSick = false, bgVal = null } = meta;
        if (isSick) {
            res.warnings = res.warnings || [];
            res.warnings.push("⚠️ Modo Enfermedad: Dosis aumentada un 20%.");
            // AUDIT FIX: Use generic threshold or check unit
            // Assuming mg/dL for now, but should ideally check units. 
            // 250 mg/dL is roughly 13.9 mmol/L. Only warn if value is extremely high.
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

    const confirmCalculation = async () => {
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

    const cancelConfirmation = () => setConfirmRequest(null);

    /**
     * Main Calculate Function
     * @param {Object} inputs - { glucose, carbs, slot, correctionOnly, etc... }
     */
    const calculate = async (inputs) => {
        const {
            glucose, carbs, slot, correctionOnly, dessertMode, dualEnabled,
            alcoholEnabled, exercise, overrideParams, carbProfile,
            orphanContext, mealMeta // orphanContext = { isUsing, orphanData }, mealMeta = { fat, protein... from Ref }
        } = inputs;

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

            // Determine Fat/Protein logic
            let fatVal = 0;
            let proteinVal = 0;
            let fiberVal = 0;

            // Priority: Orphan -> MealMeta -> State (Legacy)
            if (orphanContext?.isUsing && orphanContext?.data) {
                const oc = orphanContext.data;
                if (oc._diffMode) {
                    fatVal = oc._netFat || 0;
                    proteinVal = oc._netProtein || 0;
                    fiberVal = oc._netFiber || 0;
                } else {
                    fatVal = oc.fat || 0;
                    proteinVal = oc.protein || 0;
                    fiberVal = oc.fiber || 0;
                }
            } else if (mealMeta) {
                fatVal = mealMeta.fat || 0;
                proteinVal = mealMeta.protein || 0;
                fiberVal = mealMeta.fiber || 0;
            } else {
                // Fallback to legacy global state if not passed (though we tried to move away)
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
                finalIcr = finalIcr * 0.83;
                finalIsf = finalIsf * 0.83;
            }

            const payload = {
                carbs_g: correctionOnly ? 0 : carbsVal,
                fat_g: correctionOnly ? 0 : fatVal,
                protein_g: correctionOnly ? 0 : proteinVal,
                fiber_g: (correctionOnly) ? 0 : (fiberVal || 0),
                bg_mgdl: isNaN(bgVal) ? null : bgVal,
                meal_slot: slot,
                target_mgdl: slotParams.target,
                carb_profile: carbProfile ?? null,
                cr_g_per_u: finalIcr,
                isf_mgdl_per_u: finalIsf,
                dia_hours: mealParams.dia_hours || 4.0,
                round_step_u: mealParams.round_step_u || 0.5,
                max_bolus_u: mealParams.max_bolus_u || 15,
                warsaw_safety_factor: mealParams.warsaw?.safety_factor,
                warsaw_safety_factor_dual: mealParams.warsaw?.safety_factor_dual,
                warsaw_trigger_threshold_kcal: mealParams.warsaw?.trigger_threshold_kcal,
                use_fiber_deduction: mealParams.calculator?.subtract_fiber,
                fiber_factor: mealParams.calculator?.fiber_factor,
                fiber_threshold: mealParams.calculator?.fiber_threshold_g,
                ignore_iob: dessertMode,
                alcohol: alcoholEnabled,
                exercise: exercise || { planned: false, minutes: 0, intensity: 'moderate' },
                // SC-Compat: Use override if explicit > Use Settings > Default False (Strict User Control)
                enable_autosens: overrideParams?.useAutosens !== undefined
                    ? overrideParams.useAutosens
                    : (mealParams.autosens?.enabled || false),
                autosens_ratio: (overrideParams?.useAutosens ? (state.autosens?.ratio || 1.0) : 1.0),
                autosens_reason: state.autosens?.reason || null
            };

            let splitSettings = getSplitSettings() || {};
            splitSettings.enabled = !!(dualEnabled);

            if (alcoholEnabled && dualEnabled) {
                splitSettings.duration_min = 240;
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

    /**
     * Save Function
     */
    const save = async (saveParams) => {
        const {
            confirmedDose, siteId,
            carbs, glucose, foodName,
            orphanContext, mealMeta, // { fat, protein, fiber, items }
            date, nsConfig,
            alcoholEnabled, carbProfile,
            plateItems
        } = saveParams;

        setSaving(true);
        try {
            const finalInsulin = parseFloat(confirmedDose);
            if (isNaN(finalInsulin) || finalInsulin < 0) throw new Error("Dosis inválida");

            const customDate = new Date(date);
            let fiberNote = "";
            const explainList = result.explain || result.calc?.explain;
            if (explainList) {
                const fiberLine = explainList.find(l => l.includes('Fibra') || l.includes('Restando'));
                if (fiberLine) fiberNote = ` [${fiberLine}]`;
            }

            // Resolve actual macros used
            const isOrphan = orphanContext?.isUsing && orphanContext?.data;
            let usedFat = 0, usedProt = 0, usedFiber = 0;
            const linkedIngestion = !!(isOrphan || mealMeta?.linked_ingestion);
            const ingestionId = isOrphan ? orphanContext?.data?.id : mealMeta?.ingestion_id;

            if (isOrphan) {
                const oc = orphanContext.data;
                usedFat = oc._diffMode ? oc._netFat : oc.fat;
                usedProt = oc._diffMode ? oc._netProtein : oc.protein;
                usedFiber = oc._diffMode ? oc._netFiber : oc.fiber;
            } else if (mealMeta) {
                usedFat = mealMeta.fat;
                usedProt = mealMeta.protein;
                usedFiber = mealMeta.fiber;
            }

            // Defaults to 0 if NaN/Undefined
            usedFat = usedFat || 0;
            usedProt = usedProt || 0;
            usedFiber = usedFiber || 0;

            const treatment = {
                eventType: "Meal Bolus",
                created_at: customDate.toISOString(),
                carbs: (parseFloat(carbs) || 0),
                fat: usedFat,
                protein: usedProt,
                fiber: usedFiber,
                carb_profile: carbProfile ?? null,
                insulin: finalInsulin,
                linked_ingestion: linkedIngestion,
                ingestion_id: ingestionId || null,
                enteredBy: state.user?.username || "BolusAI",
                notes: `BolusAI: ${(result.kind === 'dual' || result.kind === 'extended') ? 'Dual' : 'Normal'}. Gr: ${carbs}${isOrphan ? ' (Sincronizado)' : ''}. BG: ${glucose}. ${foodName ? 'Comida: ' + foodName + '.' : ''} ${alcoholEnabled ? 'Alcohol Detected.' : ''} ${plateItems?.length > 0 ? 'Items: ' + plateItems.map(i => i.name).join(', ') : ''}${fiberNote}`,
                nightscout: {
                    url: nsConfig?.url || null,
                },
                injection_site: siteId || null
            };

            // Meta for Learning
            const metaItems = (mealMeta?.items?.length > 0)
                ? mealMeta.items
                : (plateItems?.length > 0 ? plateItems.map(i => i.name) : (foodName ? [foodName] : []));

            if (metaItems.length > 0 || parseFloat(carbs) > 0) {
                const strategy = (result.kind === 'dual' || result.kind === 'extended') ? {
                    kind: 'dual',
                    total: result.total_u_final,
                    upfront: result.upfront_u,
                    later: result.later_u,
                    delay: result.duration_min
                } : { kind: 'normal', total: result.total_u_final };

                treatment.meal_meta = {
                    items: metaItems,
                    fat: usedFat,
                    protein: usedProt,
                    fiber: usedFiber,
                    strategy
                };
            }

            // Dual Plan State Update
            if (result.kind === 'dual' || result.kind === 'extended') {
                treatment.notes += ` (Split: ${finalInsulin} now + ${result.later_u} delayed ${result.duration_min}m)`;
                state.lastBolusPlan = {
                    ...result.plan,
                    upfront_u: finalInsulin,
                    created_at_ts: Date.now()
                };
                saveDualPlan(state.lastBolusPlan);

                // --- SYNC TO BOT ENDPOINT ---
                try {
                    // We need to map to ActivePlan Schema
                    // result.plan usually has: { now_u, later_u_planned, later_after_min, extended_duration_min, total_recommended_u }
                    await saveActivePlan({
                        id: result.plan.plan_id || String(Date.now()),
                        created_at_ts: Date.now(),
                        upfront_u: finalInsulin,
                        later_u_planned: result.later_u, // from result top level which is already calculated/overwritten
                        later_after_min: result.duration_min, // usually same as duration
                        extended_duration_min: result.duration_min,
                        notes: `Origen: App (${foodName || 'Manual'})`,
                        status: "pending"
                    });
                } catch (errPlan) {
                    console.warn("Failed to sync plan to bot:", errPlan);
                }
            }

            if (siteId && finalInsulin > 0) {
                saveInjectionSite('rapid', siteId);
                treatment.notes += ` - Sitio: ${getSiteLabel('rapid', siteId)}`;
            }

            const apiRes = await saveTreatment(treatment);

            // Needle Stock
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

            // Restaurant Session
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

    return {
        calculate,
        save,
        confirmCalculation,
        cancelConfirmation,
        result,
        setResult,
        calcUsedParams,
        calculating,
        saving,
        confirmRequest
    };
}

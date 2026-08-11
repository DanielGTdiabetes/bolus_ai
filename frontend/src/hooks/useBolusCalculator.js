
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
    getSplitSettings,
    state,
    saveDualPlan
} from '../modules/core/store';
import { navigate } from '../modules/core/navigation';
import { showToast } from '../components/ui/Toast';
import { resolveSickModeDosingPolicy } from '../lib/sickModePolicy';
import { buildOnlineBolusPayload } from '../lib/onlineBolusPayload';
import { buildClientBolusTrace } from '../lib/bolusTrace';
import { buildPersistentDualPlan, getAuthoritativeBolusTotal } from '../lib/dualPlan';
import { addMealSessionCarbs, linkTreatmentToMealSession } from '../lib/mealSessionApi';

export function useBolusCalculator() {
    const [result, setResult] = useState(null);
    const [calcUsedParams, setCalcUsedParams] = useState(null);
    const [calculating, setCalculating] = useState(false);
    const [saving, setSaving] = useState(false);
    const [confirmRequest, setConfirmRequest] = useState(null);
    const [pendingCalcContext, setPendingCalcContext] = useState(null);

    const applyCalcOutcome = (res, meta = {}) => {
        const { isSick = false, bgVal = null, sickModeWarning = null } = meta;
        if (isSick) {
            res.warnings = res.warnings || [];
            res.warnings.push(
                sickModeWarning ||
                "⚠️ Modo Enfermedad activo: ajuste automático de dosis desactivado; se usan los ratios configurados."
            );
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

    const confirmCalculation = async (manualIobValue) => {
        if (!pendingCalcContext || !confirmRequest) return;
        setCalculating(true);
        try {
            const { payload, useSplit, splitSettings, meta } = pendingCalcContext;
            let flaggedPayload;
            if (confirmRequest.mode === "manual_iob") {
                const iobVal = parseFloat(manualIobValue);
                if (isNaN(iobVal) || iobVal < 0) {
                    alert("Introduce un valor de IOB válido (≥ 0).");
                    setCalculating(false);
                    return;
                }
                // Si llegamos al modal manual desde un flujo CONFIRM_REQUIRED, el backend
                // sigue requiriendo el flag de confirmación anterior (guard lines 444/462).
                flaggedPayload = {
                    ...payload,
                    manual_iob_u: iobVal,
                    ...(confirmRequest.prevConfirmFlag ? { [confirmRequest.prevConfirmFlag]: true } : {})
                };
            } else {
                flaggedPayload = { ...payload, [confirmRequest.requiredFlag || "confirm_iob_unknown"]: true };
            }
            const res = await calculateBolusWithOptionalSplit(flaggedPayload, useSplit ? splitSettings : null);
            applyCalcOutcome(res, meta || {});
            setConfirmRequest(null);
        } catch (err) {
            const code = err?.error_code || err?.payload?.error_code;
            if (code === "IOB_UNCERTAIN") {
                setConfirmRequest({
                    code,
                    mode: "manual_iob",
                    requiredFlag: "manual_iob_u",
                    // Preservar el flag de confirmación anterior para que el backend no rechace el retry
                    prevConfirmFlag: confirmRequest.mode === "confirm" ? confirmRequest.requiredFlag : null,
                    detail: err?.payload || {}
                });
            } else {
                alert("Error: " + (err?.message || "No se pudo confirmar sin IOB."));
            }
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
            glucose, carbs, slot, correctionOnly, dualEnabled,
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

            // Online calculations use backend settings as the single source of truth.
            // Sick mode remains context-only and does not alter browser-side ratios.
            const isSick = localStorage.getItem('sick_mode_enabled') === 'true';
            const sickModePolicy = resolveSickModeDosingPolicy({ isSick });

            const payload = buildOnlineBolusPayload({
                carbsG: correctionOnly ? 0 : carbsVal,
                fatG: correctionOnly ? 0 : fatVal,
                proteinG: correctionOnly ? 0 : proteinVal,
                fiberG: correctionOnly ? 0 : (fiberVal || 0),
                bgMgdl: isNaN(bgVal) ? null : bgVal,
                mealSlot: slot,
                carbProfile,
                alcohol: alcoholEnabled,
                exercise: exercise || { planned: false, minutes: 0, intensity: 'moderate' },
                dualBolusEnabled: !!dualEnabled,
                autosensOverride: overrideParams?.useAutosens,
            });

            let splitSettings = getSplitSettings() || {};
            splitSettings.enabled = !!(dualEnabled);

            if (alcoholEnabled && dualEnabled) {
                splitSettings.duration_min = 240;
                splitSettings.later_after_min = 240;
                showToast("🍷 Alcohol: Segunda dosis retrasada a 4h por seguridad.", "info", 4000);
            }

            const useSplit = (dualEnabled && !correctionOnly && carbsVal > 0);
            const calcMeta = {
                isSick,
                bgVal,
                sickModeWarning: sickModePolicy.warning,
            };
            setPendingCalcContext({ payload, useSplit, splitSettings: useSplit ? splitSettings : null, meta: calcMeta });

            const res = await calculateBolusWithOptionalSplit(payload, useSplit ? splitSettings : null);
            applyCalcOutcome(res, calcMeta);

        } catch (e) {
            const code = e?.error_code || e?.payload?.error_code;
            if (code === "IOB_UNCERTAIN") {
                setConfirmRequest({
                    code,
                    mode: "manual_iob",
                    requiredFlag: "manual_iob_u",
                    detail: e?.payload || {}
                });
            } else if (code && String(code).includes("CONFIRM_REQUIRED")) {
                setConfirmRequest({
                    code,
                    mode: "confirm",
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
            plateItems, mealSlot,
            mealSessionId, mealSessionPlatePayload
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
            const glucoseValue = parseFloat(glucose);
            const treatmentId = globalThis.crypto?.randomUUID?.()
                ?? `bolus-${Date.now()}-${Math.random().toString(16).slice(2)}`;
            const isDualResult = result.kind === 'dual' || result.kind === 'extended';
            const totalRecommendedU = getAuthoritativeBolusTotal(result);
            const persistentDualPlan = isDualResult ? buildPersistentDualPlan({
                result,
                treatmentId,
                acceptedUpfrontU: finalInsulin,
                createdAtTs: Date.now(),
                mealSlot: mealSlot || null,
                source: result?.plan ? 'app-manual-split' : 'app-engine-split',
            }) : null;

            const treatment = {
                treatment_id: treatmentId,
                eventType: "Meal Bolus",
                created_at: customDate.toISOString(),
                carbs: (parseFloat(carbs) || 0),
                glucose: Number.isFinite(glucoseValue) ? glucoseValue : null,
                fat: usedFat,
                protein: usedProt,
                fiber: usedFiber,
                carb_profile: carbProfile ?? null,
                insulin: finalInsulin,
                linked_ingestion: linkedIngestion,
                ingestion_id: ingestionId || null,
                enteredBy: state.user?.username || "BolusAI",
                notes: `BolusAI: ${isDualResult ? 'Dual' : 'Normal'}. Gr: ${carbs}${isOrphan ? ' (Sincronizado)' : ''}. BG: ${glucose}. ${foodName ? 'Comida: ' + foodName + '.' : ''} ${alcoholEnabled ? 'Alcohol Detected.' : ''} ${plateItems?.length > 0 ? 'Items: ' + plateItems.map(i => i.name).join(', ') : ''}${fiberNote}`,
                nightscout: {
                    url: nsConfig?.url || null,
                },
                calculation_trace: buildClientBolusTrace(result, finalInsulin, 'app'),
                injection_site: siteId || null
            };

            // Meta for Learning
            const metaItems = (mealMeta?.items?.length > 0)
                ? mealMeta.items
                : (plateItems?.length > 0 ? plateItems.map(i => i.name) : (foodName ? [foodName] : []));

            if (metaItems.length > 0 || parseFloat(carbs) > 0) {
                const strategy = persistentDualPlan ? {
                    kind: 'dual',
                    total: totalRecommendedU,
                    upfront: persistentDualPlan.upfront_u,
                    later: persistentDualPlan.later_u_planned,
                    delay: persistentDualPlan.later_after_min,
                    plan_id: persistentDualPlan.plan_id,
                    treatment_id: treatmentId,
                } : { kind: 'normal', total: totalRecommendedU };

                treatment.meal_meta = {
                    items: metaItems,
                    fat: usedFat,
                    protein: usedProt,
                    fiber: usedFiber,
                    strategy
                };
            }

            // Add the plan description to the treatment, but do not mark the
            // plan active until the treatment itself has been persisted.
            if (persistentDualPlan) {
                treatment.notes += ` (Split: ${persistentDualPlan.upfront_u} now + ${persistentDualPlan.later_u_planned} delayed ${persistentDualPlan.later_after_min}m)`;
            }

            if (siteId && finalInsulin > 0) {
                saveInjectionSite('rapid', siteId);
                treatment.notes += ` - Sitio: ${getSiteLabel('rapid', siteId)}`;
            }

            const apiRes = await saveTreatment(treatment);

            // Long-meal ledger is deliberately post-treatment and best-effort.
            // A ledger failure must never invalidate an already persisted bolus.
            let mealSessionState = null;
            let mealSessionPlateRecorded = !mealSessionPlatePayload;
            let mealSessionLinked = false;
            if (mealSessionId) {
                if (mealSessionPlatePayload) {
                    try {
                        mealSessionState = await addMealSessionCarbs(mealSessionId, mealSessionPlatePayload);
                        mealSessionPlateRecorded = true;
                    } catch (sessionErr) {
                        console.warn("Failed to record meal-session plate:", sessionErr);
                        showToast("⚠️ Bolo guardado, pero el plato no se pudo añadir a la sesión.", "warning", 5000);
                    }
                }

                if (apiRes?.treatment_id) {
                    try {
                        mealSessionState = await linkTreatmentToMealSession(mealSessionId, apiRes.treatment_id);
                        mealSessionLinked = true;
                    } catch (sessionErr) {
                        console.warn("Failed to link treatment to meal session:", sessionErr);
                        showToast("⚠️ Bolo guardado, pero no se pudo vincular a la comida larga.", "warning", 5000);
                    }
                }
            }

            // Activate/sync the plan only after treatment persistence succeeded.
            if (persistentDualPlan && apiRes?.success !== false) {
                state.lastBolusPlan = persistentDualPlan;
                saveDualPlan(persistentDualPlan);
                try {
                    await saveActivePlan({
                        ...persistentDualPlan,
                        notes: `Origen: App (${foodName || 'Manual'})`,
                    });
                } catch (errPlan) {
                    console.warn("Failed to sync plan to bot:", errPlan);
                }
            }

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
            if (mealSessionId) {
                setResult(null);
                return {
                    ...apiRes,
                    meal_session: mealSessionState,
                    meal_session_plate_recorded: mealSessionPlateRecorded,
                    meal_session_linked: mealSessionLinked,
                };
            }

            setTimeout(() => navigate('#/'), 1000);
            return apiRes;

        } catch (e) {
            alert("Error guardando: " + e.message);
            return null;
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

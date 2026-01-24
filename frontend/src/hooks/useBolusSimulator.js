
import { useState, useCallback } from 'react';
import { getIOBData, fetchTreatments, simulateForecast } from '../lib/api';
import { buildHistoryFromSnapshot, shouldDegradeSimulation, buildForecastPayload } from '../pages/bolusSimulationUtils';

export function useBolusSimulator() {
    const [predictionData, setPredictionData] = useState(null);
    const [simulating, setSimulating] = useState(false);

    /**
     * Run Forecast Simulation
     * @param {Object} context - { doseNow, doseLater, carbsVal, params, slot, carbProfile, dessertMode, result, nsConfig }
     */
    const runSimulation = useCallback(async (context) => {
        const {
            doseNow, doseLater, carbsVal,
            params, slot, carbProfile,
            dessertMode, result, nsConfig,
            settingsAbsorption, mealMeta
        } = context;

        setSimulating(true);
        setPredictionData(null);
        try {
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
            let bgVal = result?.glucose?.mgdl;
            if (!bgVal || bgVal <= 0) {
                if (targetMgdl) {
                    bgVal = targetMgdl;
                } else {
                    // Fallback to safe value?
                    bgVal = 120;
                }
            }

            // Build events
            const boluses = [];
            const nowU = isNaN(doseNow) ? 0 : doseNow;
            if (nowU > 0) boluses.push({ time_offset_min: 0, units: nowU });

            const extU = isNaN(doseLater) ? 0 : doseLater;
            if (extU > 0) {
                boluses.push({
                    time_offset_min: 0,
                    units: extU,
                    duration_minutes: result?.duration_min || 120
                });
            }

            const currentCarbs = parseFloat(carbsVal) || 0;
            const primaryCarbs = currentCarbs > 0 ? [{
                time_offset_min: 0,
                grams: currentCarbs,
                carb_profile: carbProfile,
                is_dessert: dessertMode,
                // Include Fat/Protein for Auto-Absorption Logic
                fat_g: mealMeta?.fat || 0,
                protein_g: mealMeta?.protein || 0,
                fiber_g: mealMeta?.fiber || 0
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

            // Determine Onset based on Settings (Insulin Name/Type) - Source of Truth
            // We use settings.insulin.name, falling back to params if needed
            const settingsInsulinName = context.settings?.insulin?.name || "";
            const modelLower = (settingsInsulinName || insulinModel || "").toLowerCase();

            let insulinOnset = 10; // Default
            if (modelLower.includes('fiasp') || modelLower.includes('lyumjev')) {
                insulinOnset = 5;
            } else if (modelLower.includes('novorapid') || modelLower.includes('aspart') ||
                modelLower.includes('humalog') || modelLower.includes('lispro') ||
                modelLower.includes('apidra')) {
                insulinOnset = 15;
            }

            const payload = buildForecastPayload({
                bgVal,
                targetMgdl,
                isf,
                icr,
                dia,
                peak,
                insulinModel,
                carbAbsorption: (settingsAbsorption?.[slot] || 180),
                basalDailyUnits: params.tdd_u ? (params.tdd_u * 0.5) : undefined,
                insulinOnset,
                settings: context.settings,
                slot,
                events
            });

            const res = await simulateForecast(payload);
            setPredictionData(res);

        } catch (err) {
            console.warn("Forecast Sim error", err);
        } finally {
            setSimulating(false);
        }
    }, []);

    return {
        predictionData,
        simulating,
        runSimulation
    };
}

import { useState, useCallback } from 'react';
import { fetchTreatments } from '../lib/api';

function parseCoveredCarbs(notes) {
    if (!notes) return null;

    const explicit = notes.match(/\[covered_carbs=([0-9]+(?:[.,][0-9]+)?)\]/i);
    if (explicit) {
        const parsed = Number(explicit[1].replace(',', '.'));
        return Number.isFinite(parsed) ? parsed : null;
    }

    // Legacy/current BolusAI notes preserve the dose-context carbs as "Gr: X"
    // even when Treatment.carbs is deliberately stored as 0 for linked ingestions
    // to avoid duplicating COB.
    const legacy = notes.match(/\bGr:\s*([0-9]+(?:[.,][0-9]+)?)/i);
    if (legacy) {
        const parsed = Number(legacy[1].replace(',', '.'));
        return Number.isFinite(parsed) ? parsed : null;
    }

    return null;
}

function isLinkedToIngestion(treatment, ingestionId) {
    if (!treatment?.notes || !ingestionId) return false;
    return treatment.notes.includes(`[linked_ingestion_id=${ingestionId}]`);
}

/**
 * Detecta una ingesta nutricional sin insulina asociada y, cuando esa misma
 * ingesta se actualiza de forma acumulativa (por ejemplo 40 g -> 60 g), ofrece
 * únicamente los HC nuevos todavía no cubiertos.
 *
 * La identidad de la ingesta es obligatoria para descontar cobertura previa.
 * Nunca se suman bolos "Sincronizado" globales de otras comidas.
 */
export function useOrphanDetection() {
    const [orphanCarbs, setOrphanCarbs] = useState(null);
    const [isUsingOrphan, setIsUsingOrphan] = useState(false);

    const checkOrphans = useCallback(async () => {
        try {
            const treatments = await fetchTreatments({ count: 30 });
            if (!treatments || treatments.length === 0) {
                setOrphanCarbs(null);
                return;
            }

            const now = new Date();
            const orphans = treatments.filter((t) => {
                const tDate = new Date(t.created_at);
                const diffMin = (now.getTime() - tDate.getTime()) / 60000;
                const hasNutrition = (t.carbs > 0 || t.fat > 0 || t.protein > 0);
                return hasNutrition && (!t.insulin || t.insulin === 0) && diffMin > -5 && diffMin < 60;
            });

            if (orphans.length === 0) {
                setOrphanCarbs(null);
                return;
            }

            orphans.sort((a, b) => {
                const sumA = (a.carbs || 0) + (a.fat || 0) + (a.protein || 0);
                const sumB = (b.carbs || 0) + (b.fat || 0) + (b.protein || 0);
                return sumB - sumA;
            });

            const bestOrphan = orphans[0];
            const adjustedOrphan = { ...bestOrphan };

            // Only boluses explicitly linked to THIS ingestion can count as covered.
            // This prevents a nearby unrelated meal from reducing the new-carbs delta.
            const linkedSaves = treatments.filter((t) => {
                const tDate = new Date(t.created_at);
                const diffMin = (now.getTime() - tDate.getTime()) / 60000;
                return diffMin > -5 && diffMin < 180 && isLinkedToIngestion(t, bestOrphan.id);
            });

            const coveredEntries = linkedSaves
                .map((t) => {
                    const parsed = parseCoveredCarbs(t.notes);
                    if (parsed !== null) return parsed;
                    // Legacy fallback only when the linked treatment actually kept carbs.
                    const stored = Number(t.carbs || 0);
                    return Number.isFinite(stored) && stored > 0 ? stored : 0;
                })
                .filter((value) => value > 0);

            // Each linked bolus records how many NEW carbs that calculation covered.
            const alreadyApplied = coveredEntries.reduce((sum, value) => sum + value, 0);
            const totalCarbs = Number(bestOrphan.carbs || 0);
            const diffCarbs = Math.max(0, totalCarbs - alreadyApplied);

            if (alreadyApplied > 0) {
                adjustedOrphan._diffMode = true;
                adjustedOrphan._originalCarbs = totalCarbs;
                adjustedOrphan._alreadyApplied = alreadyApplied;
                adjustedOrphan._netCarbs = diffCarbs;

                // Macro deltas are best-effort only. Carbs are the dosing-critical contract.
                // Linked bolus Treatment rows intentionally store macros as zero to avoid COB
                // duplication, so we do not infer previous fat/protein/fiber from unrelated rows.
                adjustedOrphan._netFat = bestOrphan.fat || 0;
                adjustedOrphan._netProtein = bestOrphan.protein || 0;
                adjustedOrphan._netFiber = bestOrphan.fiber || 0;
            }

            // Small source corrections at/below the already-covered amount should not
            // create a new dosing prompt.
            if (diffCarbs <= 2 && alreadyApplied > 0) {
                adjustedOrphan._fullyCovered = true;
            }

            setOrphanCarbs(adjustedOrphan._fullyCovered ? null : adjustedOrphan);
        } catch (err) {
            console.warn('Failed to fetch recent treatments for orphan detection', err);
        }
    }, []);

    const dismissOrphan = () => {
        setOrphanCarbs(null);
        setIsUsingOrphan(false);
    };

    return {
        orphanCarbs,
        isUsingOrphan,
        setIsUsingOrphan,
        checkOrphans,
        dismissOrphan,
    };
}

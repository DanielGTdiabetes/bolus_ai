import { useState, useCallback } from 'react';
import { fetchTreatments } from '../lib/api';
import {
    calculateCoveredCarbsForIngestion,
    calculateNewCarbsToCover,
    isLinkedToIngestion,
} from '../lib/orphanCarbsCore';

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
            const linkedSaves = treatments.filter((t) => {
                const tDate = new Date(t.created_at);
                const diffMin = (now.getTime() - tDate.getTime()) / 60000;
                return diffMin > -5 && diffMin < 180 && isLinkedToIngestion(t, bestOrphan.id);
            });

            const alreadyApplied = calculateCoveredCarbsForIngestion(linkedSaves, bestOrphan.id);
            const totalCarbs = Number(bestOrphan.carbs || 0);
            const diffCarbs = calculateNewCarbsToCover(totalCarbs, alreadyApplied);

            if (alreadyApplied > 0) {
                adjustedOrphan._diffMode = true;
                adjustedOrphan._originalCarbs = totalCarbs;
                adjustedOrphan._alreadyApplied = alreadyApplied;
                adjustedOrphan._netCarbs = diffCarbs;

                // Macro deltas remain best-effort. Treatment macros for linked boluses
                // are intentionally zero to prevent COB duplication.
                adjustedOrphan._netFat = bestOrphan.fat || 0;
                adjustedOrphan._netProtein = bestOrphan.protein || 0;
                adjustedOrphan._netFiber = bestOrphan.fiber || 0;
            }

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

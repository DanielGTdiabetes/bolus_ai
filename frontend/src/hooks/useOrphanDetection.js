
import { useState, useEffect, useCallback } from 'react';
import { fetchTreatments } from '../lib/api';

/**
 * Hook to detect "Orphan Carbs" (treatments with carbs but no insulin)
 * created in the last 60 minutes.
 * 
 * @returns {Object} { orphanCarbs, isUsingOrphan, setIsUsingOrphan, checkOrphans, dismissOrphan }
 */
export function useOrphanDetection() {
    const [orphanCarbs, setOrphanCarbs] = useState(null);
    const [isUsingOrphan, setIsUsingOrphan] = useState(false);

    const checkOrphans = useCallback(async () => {
        try {
            const treatments = await fetchTreatments({ count: 10 });
            if (!treatments || treatments.length === 0) return;

            const now = new Date();
            // Find ALL potential orphans in the last 60 mins
            const orphans = treatments.filter(t => {
                const tDate = new Date(t.created_at);
                const diffMin = (now.getTime() - tDate.getTime()) / 60000;
                const hasNutrition = (t.carbs > 0 || t.fat > 0 || t.protein > 0);
                // Standard orphan check: Has nutrition, NO insulin (or 0), and recent (-5 to 60min)
                return hasNutrition && (!t.insulin || t.insulin === 0) && diffMin > -5 && diffMin < 60;
            });

            if (orphans.length > 0) {
                // Sort by "Data Richness" (Carbs + Fat + Protein sum) DESC
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
                } else {
                    setOrphanCarbs(null);
                }
            } else {
                 setOrphanCarbs(null);
            }
        } catch (err) {
            console.warn("Failed to fetch recent treatments for orphan detection", err);
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
        dismissOrphan
    };
}

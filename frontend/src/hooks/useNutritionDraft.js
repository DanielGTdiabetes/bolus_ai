
import { useState, useCallback } from 'react';
import { getNutritionDraft, closeNutritionDraft, discardNutritionDraft } from '../lib/api';
import { showToast } from '../components/ui/Toast';

/**
 * Hook to manage "Nutrition Drafts" (incoming meals from Bot/External)
 * @returns {Object} { draft, setDraft, checkDraft, applyDraft, discard, loadingDraft }
 */
export function useNutritionDraft() {
    const [draft, setDraft] = useState(null);
    const [loadingDraft, setLoadingDraft] = useState(false);

    const checkDraft = useCallback(async () => {
        try {
            const dr = await getNutritionDraft();
            if (dr && dr.active && dr.draft) {
                setDraft(dr.draft);
            } else {
                setDraft(null);
            }
        } catch (err) {
            console.warn("Draft check failed", err);
        }
    }, []);

    const applyDraft = useCallback(async (onSuccess) => {
        if (!draft) return;
        setLoadingDraft(true);
        try {
            await closeNutritionDraft();
            showToast("✅ Borrador aplicado.", "success");

            // Pass the draft data back to the caller (UI) to populate fields
            if (onSuccess) onSuccess(draft);

            setDraft(null);
        } catch (e) {
            console.error(e);
            showToast("Aplicado localmente (error cerrando en servidor)", "warning");
            // Still perform success action locally
            if (onSuccess) onSuccess(draft);
            setDraft(null);
        } finally {
            setLoadingDraft(false);
        }
    }, [draft]);

    const discard = useCallback(async () => {
        if (!draft) return;
        setLoadingDraft(true);
        try {
            await discardNutritionDraft();
            setDraft(null);
        } catch (e) {
            console.error(e);
            setDraft(null); // Clear anyway
        } finally {
            setLoadingDraft(false);
        }
    }, [draft]);

    return {
        draft,
        setDraft,
        checkDraft,
        applyDraft,
        discard,
        loadingDraft
    };
}

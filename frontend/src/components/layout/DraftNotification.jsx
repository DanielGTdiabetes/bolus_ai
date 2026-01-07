import React, { useEffect, useRef, useState } from 'react';
import { getNutritionDraft, closeNutritionDraft, discardNutritionDraft, isAuthenticated } from '../../lib/api';
import { Button } from '../ui/Atoms';
import { useInterval } from '../../hooks/useInterval';
import { showToast } from '../ui/Toast';

const LAST_SEEN_DRAFT_KEY = 'bolusai_last_seen_draft_v2';

export function DraftNotification() {
    const [currentDraft, setCurrentDraft] = useState(null);
    const [showModal, setShowModal] = useState(false);
    const [pollDelay, setPollDelay] = useState(5000);
    const [isVisible, setIsVisible] = useState(() => document.visibilityState === 'visible');
    const errorCountRef = useRef(0);
    const lastSeenRef = useRef(localStorage.getItem(LAST_SEEN_DRAFT_KEY));

    const markSeen = (draft) => {
        if (!draft?.id) return;
        const key = `${draft.id}|${draft.updated_at}`;
        localStorage.setItem(LAST_SEEN_DRAFT_KEY, key);
        lastSeenRef.current = key;
    };

    const pollDraft = async () => {
        // Don't poll if user is not authenticated - prevents infinite 401 loop
        if (!isAuthenticated()) {
            return;
        }
        try {
            const payload = await getNutritionDraft();
            errorCountRef.current = 0;
            setPollDelay(5000);

            if (payload?.active && payload?.draft?.id) {
                const nextDraft = payload.draft;
                setCurrentDraft(nextDraft);

                const currentKey = `${nextDraft.id}|${nextDraft.updated_at}`;
                if (currentKey !== lastSeenRef.current) {
                    setShowModal(true);
                }
                return;
            }

            setCurrentDraft(null);
            setShowModal(false);
        } catch (error) {
            errorCountRef.current += 1;
            setPollDelay(errorCountRef.current >= 2 ? 30000 : 15000);
        }
    };

    useInterval(() => {
        if (isVisible) {
            pollDraft();
        }
    }, isVisible ? pollDelay : null);

    useEffect(() => {
        const handleVisibility = () => setIsVisible(document.visibilityState === 'visible');
        document.addEventListener('visibilitychange', handleVisibility);
        pollDraft();
        return () => document.removeEventListener('visibilitychange', handleVisibility);
    }, []);

    const handleDismiss = () => {
        if (currentDraft?.id) {
            markSeen(currentDraft);
        }
        setShowModal(false);
    };

    const handleConfirm = async () => {
        if (!currentDraft?.id) return;
        try {
            await closeNutritionDraft();
            markSeen(currentDraft);
            setShowModal(false);
            setCurrentDraft(null);
            showToast("✅ Draft confirmado.", "success");
        } catch (error) {
            showToast(error.message || "Error confirmando draft.", "error");
        }
    };

    const handleDiscard = async () => {
        if (!currentDraft?.id) return;
        try {
            await discardNutritionDraft();
            markSeen(currentDraft);
            setShowModal(false);
            setCurrentDraft(null);
            showToast("Draft descartado.", "info");
        } catch (error) {
            showToast(error.message || "Error descartando draft.", "error");
        }
    };

    if (!showModal || !currentDraft) return null;

    const macros = {
        carbs: Number(currentDraft?.carbs ?? 0),
        fat: Number(currentDraft?.fat ?? 0),
        protein: Number(currentDraft?.protein ?? 0),
        fiber: Number(currentDraft?.fiber ?? 0)
    };

    return (
        <div className="draft-modal-backdrop" role="presentation">
            <div className="draft-modal" role="dialog" aria-modal="true" aria-label="Nuevo alimento pendiente">
                <div className="draft-modal-header">
                    <h3>Nuevo alimento pendiente</h3>
                    <button type="button" className="draft-modal-close" onClick={handleDismiss} aria-label="Cerrar">
                        ×
                    </button>
                </div>
                <div className="draft-modal-body">
                    <p>Se detectó un borrador activo con los siguientes macros:</p>
                    <div className="draft-modal-macros">
                        <div>
                            <strong>{Math.round(macros.carbs)}g</strong>
                            <span>Carbs</span>
                        </div>
                        <div>
                            <strong>{Math.round(macros.fat)}g</strong>
                            <span>Grasa</span>
                        </div>
                        <div>
                            <strong>{Math.round(macros.protein)}g</strong>
                            <span>Prot</span>
                        </div>
                        <div>
                            <strong>{Math.round(macros.fiber)}g</strong>
                            <span>Fibra</span>
                        </div>
                    </div>
                    <p className="draft-modal-note">El totalizador solo considera tratamientos confirmados.</p>
                </div>
                <div className="draft-modal-actions">
                    <Button onClick={handleDiscard} variant="ghost">
                        Descartar
                    </Button>
                    <Button onClick={handleConfirm}>
                        Aceptar
                    </Button>
                </div>
            </div>
        </div>
    );
}

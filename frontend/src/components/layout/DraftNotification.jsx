import React, { useEffect, useRef, useState } from 'react';
import { getNutritionDraft, closeNutritionDraft, discardNutritionDraft, updateNutritionDraft, isAuthenticated } from '../../lib/api';
import { Button } from '../ui/Atoms';
import { showToast } from '../ui/Toast';
import { Edit2, Check, X } from 'lucide-react';

const LAST_SEEN_DRAFT_KEY = 'bolusai_last_seen_draft_v2';

const safeStorageGet = (key) => {
    try {
        return localStorage.getItem(key);
    } catch (error) {
        console.warn("Draft storage unavailable", error);
        return null;
    }
};

const safeStorageSet = (key, value) => {
    try {
        localStorage.setItem(key, value);
    } catch (error) {
        console.warn("Draft storage unavailable", error);
    }
};

export function DraftNotification() {
    const [currentDraft, setCurrentDraft] = useState(null);
    const [showModal, setShowModal] = useState(false);
    const [isVisible, setIsVisible] = useState(() => document.visibilityState === 'visible');
    const [isEditing, setIsEditing] = useState(false);
    const [editCarbs, setEditCarbs] = useState("");
    const [editFat, setEditFat] = useState("");
    const [editProtein, setEditProtein] = useState("");
    const [editFiber, setEditFiber] = useState("");
    const lastSeenRef = useRef(safeStorageGet(LAST_SEEN_DRAFT_KEY));

    const markSeen = (draft) => {
        if (!draft?.id) return;
        const key = `${draft.id}|${draft.updated_at}`;
        safeStorageSet(LAST_SEEN_DRAFT_KEY, key);
        lastSeenRef.current = key;
    };

    const pollDraft = async () => {
        if (!isAuthenticated()) {
            return;
        }
        try {
            const payload = await getNutritionDraft();

            if (payload?.active && payload?.draft?.id) {
                const nextDraft = payload.draft;

                // If ID is same but carbs changed, notify again?
                // The key includes updated_at, so yes, it will show modal if time changed.

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
            console.warn("Draft check failed", error);
        }
    };

    useEffect(() => {
        const handleVisibility = () => setIsVisible(document.visibilityState === 'visible');
        const handleHashChange = () => {
            if (document.visibilityState === 'visible' && isAuthenticated()) {
                pollDraft();
            }
        };
        const handleLogout = () => {
            setCurrentDraft(null);
            setShowModal(false);
            setIsEditing(false);
        };

        document.addEventListener('visibilitychange', handleVisibility);
        window.addEventListener('hashchange', handleHashChange);
        window.addEventListener('auth:logout', handleLogout);

        if (isAuthenticated()) {
            pollDraft();
        }
        const interval = setInterval(() => {
            if (document.visibilityState === 'visible' && isAuthenticated()) pollDraft();
        }, 30000); // Poll every 30s to catch mobile ingest updates

        return () => {
            document.removeEventListener('visibilitychange', handleVisibility);
            window.removeEventListener('hashchange', handleHashChange);
            window.removeEventListener('auth:logout', handleLogout);
            clearInterval(interval);
        };
    }, []);

    useEffect(() => {
        if (isVisible && isAuthenticated()) {
            pollDraft();
        }
    }, [isVisible]);

    const handleDismiss = () => {
        if (currentDraft?.id) {
            markSeen(currentDraft);
        }
        setShowModal(false);
        setIsEditing(false);
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

    const startEditing = () => {
        setEditCarbs(String(Math.round(currentDraft?.carbs || 0)));
        setEditFat(String(Math.round(currentDraft?.fat || 0)));
        setEditProtein(String(Math.round(currentDraft?.protein || 0)));
        setEditFiber(String(Math.round(currentDraft?.fiber || 0)));
        setIsEditing(true);
    };

    const saveEdit = async () => {
        if (!currentDraft?.id) return;
        const c = parseFloat(editCarbs) || 0;
        const f = parseFloat(editFat) || 0;
        const p = parseFloat(editProtein) || 0;
        const fib = parseFloat(editFiber) || 0;

        if (c < 0 || f < 0 || p < 0 || fib < 0) {
            showToast("Introduce valores válidos", "error");
            return;
        }

        try {
            await updateNutritionDraft(currentDraft.id, { carbs: c, fat: f, protein: p, fiber: fib });
            // Optimistic update
            setCurrentDraft({
                ...currentDraft,
                carbs: c,
                fat: f,
                protein: p,
                fiber: fib,
                updated_at: new Date().toISOString()
            });
            setIsEditing(false);
            showToast("Nutrientes actualizados", "success");

            // Should we force re-poll?
            setTimeout(pollDraft, 500);

        } catch (error) {
            showToast(error.message || "Error guardando cambios", "error");
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
                        <div className="draft-macro-col">
                            {isEditing ? (
                                <input
                                    type="number"
                                    className="w-16 p-1 border rounded text-center text-black"
                                    value={editCarbs}
                                    onChange={(e) => setEditCarbs(e.target.value)}
                                    autoFocus
                                />
                            ) : (
                                <div className="flex items-center gap-2">
                                    <strong>{Math.round(macros.carbs)}g</strong>
                                    <button onClick={startEditing} className="text-gray-400 hover:text-blue-500" title="Editar">
                                        <Edit2 size={14} />
                                    </button>
                                </div>
                            )}
                            <span>Carbs</span>
                        </div>
                        <div className="draft-macro-col">
                            {isEditing ? (
                                <input
                                    type="number"
                                    className="w-16 p-1 border rounded text-center text-black"
                                    value={editFat}
                                    onChange={(e) => setEditFat(e.target.value)}
                                />
                            ) : (
                                <strong>{Math.round(macros.fat)}g</strong>
                            )}
                            <span>Grasa</span>
                        </div>
                        <div className="draft-macro-col">
                            {isEditing ? (
                                <input
                                    type="number"
                                    className="w-16 p-1 border rounded text-center text-black"
                                    value={editProtein}
                                    onChange={(e) => setEditProtein(e.target.value)}
                                />
                            ) : (
                                <strong>{Math.round(macros.protein)}g</strong>
                            )}
                            <span>Prot</span>
                        </div>
                        <div className="draft-macro-col">
                            {isEditing ? (
                                <div className="flex items-center gap-1">
                                    <input
                                        type="number"
                                        className="w-16 p-1 border rounded text-center text-black"
                                        value={editFiber}
                                        onChange={(e) => setEditFiber(e.target.value)}
                                    />
                                    <div className="flex flex-col gap-1 ml-1">
                                        <button onClick={saveEdit} className="p-1 bg-green-500 text-white rounded hover:bg-green-600"><Check size={12} /></button>
                                        <button onClick={() => setIsEditing(false)} className="p-1 bg-gray-400 text-white rounded hover:bg-gray-500"><X size={12} /></button>
                                    </div>
                                </div>
                            ) : (
                                <strong>{Math.round(macros.fiber)}g</strong>
                            )}
                            <span>Fibra</span>
                        </div>
                    </div>
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

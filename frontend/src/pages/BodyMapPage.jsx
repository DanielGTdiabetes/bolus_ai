import React, { useState } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { InjectionSiteSelector, saveInjectionSite } from '../components/injection/InjectionSiteSelector';
import { Card } from '../components/ui/Atoms';
import { apiFetch, getStoredToken } from '../lib/api';

export default function BodyMapPage() {
    // We use isolated state because the InjectionSelector manages its own history read,
    // but we want to allow "Visual Edit" without triggering "Next Recommendation" logic in a confusing way.
    // However, the component is built to be smart.
    // If we want to "Edit History", we basically just need to select a spot and save it to overwrite "Last Used".

    // But wait, "Last Used" is just one point. The user asked for "Puntos Libres y Utilizados".
    // Currently our simple logic only tracks *THE* last used point per type.
    // To show a full heatmap of history, we'd need to store more history (e.g. array of last 10 injections).
    // For now, let's stick to the current logic: Show/Edit the "Current State" (Last injection).

    const [selectedRapid, setSelectedRapid] = useState(null);
    const [selectedBasal, setSelectedBasal] = useState(null);



    // Helper to sync with backend (fixes bot sync issue)
    // Helper to sync with backend (fixes bot sync issue)
    const syncWithBackend = async (type, fullId) => {
        try {
            const token = getStoredToken();
            if (token) {
                const res = await apiFetch(`/api/injection/manual?t=${Date.now()}`, {
                    method: 'POST',
                    body: JSON.stringify({
                        insulin_type: type,
                        point_id: fullId
                    })
                });

                let textBody = "";
                try {
                    textBody = await res.text();
                } catch (readErr) {
                    textBody = "[Stream Read Error]";
                }

                let success = false;
                if (res.ok) {
                    console.log(`[BodyMap] Sync POST ${res.status}. Response: ${textBody}`);
                    success = true;
                } else {
                    console.error(`[BodyMap] Sync POST failed with status: ${res.status}. Body: ${textBody}`);
                }
                if (!success) {
                    console.error("[BodyMap] ⚠️ Sync completely failed even after fallback.");
                }
            } else {
                console.warn("[BodyMap] No auth token found, cannot sync with backend");
            }
        } catch (e) {
            console.error("[BodyMap] Failed to sync with backend:", e);
        }
    };

    const handleRapidChange = async (id) => {
        if (window.confirm("¿Marcar este punto como el ÚLTIMO utilizado?")) {
            setSelectedRapid(id); // Optimistic UI update
            saveInjectionSite('rapid', id);
            await syncWithBackend('rapid', id); // Sync in background
        }
    };

    const handleBasalChange = async (id) => {
        if (window.confirm("¿Marcar este punto como el ÚLTIMO utilizado?")) {
            setSelectedBasal(id); // Optimistic UI update
            saveInjectionSite('basal', id);
            await syncWithBackend('basal', id);
        }
    };

    return (
        <>
            <Header title="Mapa Corporal" showBack={true} />
            <main className="page" style={{ paddingBottom: '90px' }}>
                <Card className="stack">
                    <h3 style={{ marginTop: 0 }}>Estado de Rotación</h3>
                    <p style={{ fontSize: '0.9rem', color: '#64748b' }}>
                        Aquí puedes ver tu estado actual. Los puntos rojos son los últimos usados. Los verdes son los sugeridos para hoy.
                        <br /><br />
                        <strong>Para corregir:</strong> Toca cualquier punto para marcarlo manualmente como "Último utilizado".
                    </p>

                    <div style={{ marginTop: '2rem' }}>
                        <InjectionSiteSelector
                            type="rapid"
                            selected={selectedRapid}
                            forcedLastUsed={selectedRapid}
                            onSelect={handleRapidChange}
                            autoSelect={false}
                        />
                    </div>

                    <div style={{ marginTop: '3rem', borderTop: '1px dashed #cbd5e1', paddingTop: '2rem' }}>
                        <InjectionSiteSelector
                            type="basal"
                            selected={selectedBasal}
                            forcedLastUsed={selectedBasal}
                            onSelect={handleBasalChange}
                            autoSelect={false}
                        />
                    </div>
                </Card>
            </main>
            <BottomNav activeTab="menu" />
        </>
    );
}

import React, { useState } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { InjectionSiteSelector, saveInjectionSite } from '../components/injection/InjectionSiteSelector';
import { Card } from '../components/ui/Atoms';

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

    const [refreshKey, setRefreshKey] = useState(0);

    // Helper to sync with backend (fixes bot sync issue)
    const syncWithBackend = async (type, fullId) => {
        try {
            const token = localStorage.getItem('bolusai_token'); // Correct key name
            if (token) {
                const res = await fetch(`${import.meta.env.VITE_API_URL || ''}/api/injection/rotate`, {
                    method: 'POST',
                    headers: {
                        "Authorization": `Bearer ${token}`,
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        type: type === 'rapid' ? 'bolus' : 'basal',
                        target: fullId
                    })
                });

                if (res.ok) {
                    const text = await res.text();
                    if (!text) {
                        console.error("[BodyMap] ⚠️ Ghost response detected! (Empty 200 OK). Service Worker might be intercepting.");
                        alert("Error de conexión (SW Ghost). Recarga la página.");
                    } else {
                        console.log(`[BodyMap] Synced ${type} site successfully. Server said:`, text);
                    }
                } else {
                    console.error("[BodyMap] Server error:", res.status);
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
            saveInjectionSite('rapid', id);
            await syncWithBackend('rapid', id); // Sync with backend for bot
            setSelectedRapid(id);
            setRefreshKey(prev => prev + 1); // Force re-render of children to pick up localStorage change
        }
    };

    const handleBasalChange = async (id) => {
        if (window.confirm("¿Marcar este punto como el ÚLTIMO utilizado?")) {
            saveInjectionSite('basal', id);
            await syncWithBackend('basal', id); // Sync with backend for bot
            setSelectedBasal(id);
            setRefreshKey(prev => prev + 1);
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
                            key={'rapid-' + refreshKey}
                            type="rapid"
                            selected={selectedRapid}
                            onSelect={handleRapidChange}
                            autoSelect={false}
                        />
                    </div>

                    <div style={{ marginTop: '3rem', borderTop: '1px dashed #cbd5e1', paddingTop: '2rem' }}>
                        <InjectionSiteSelector
                            key={'basal-' + refreshKey}
                            type="basal"
                            selected={selectedBasal}
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

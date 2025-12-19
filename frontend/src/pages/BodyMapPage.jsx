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

    const handleRapidChange = (id) => {
        setSelectedRapid(id);
        if (confirm("¿Marcar este punto como el ÚLTIMO utilizado (corregir historial)?")) {
            saveInjectionSite('rapid', id);
            // Force reload by re-mounting or just alert
            alert("Historial actualizado.");
            window.location.reload();
        }
    };

    const handleBasalChange = (id) => {
        setSelectedBasal(id);
        if (confirm("¿Marcar este punto como el ÚLTIMO utilizado (corregir historial)?")) {
            saveInjectionSite('basal', id);
            alert("Historial actualizado.");
            window.location.reload();
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
                            onSelect={handleRapidChange}
                        />
                    </div>

                    <div style={{ marginTop: '3rem', borderTop: '1px dashed #cbd5e1', paddingTop: '2rem' }}>
                        <InjectionSiteSelector
                            type="basal"
                            selected={selectedBasal}
                            onSelect={handleBasalChange}
                        />
                    </div>
                </Card>
            </main>
            <BottomNav activeTab="menu" />
        </>
    );
}

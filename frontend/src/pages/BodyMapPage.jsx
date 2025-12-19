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
        if (confirm("¿Marcar este punto como el ÚLTIMO utilizado?")) {
            saveInjectionSite('rapid', id);
            setSelectedRapid(id); // Optimistic update
            // We need to trigger a re-render of the Selector to pick up the new "Last Used" visual
            // A simple way is to toggle a key, or we can just rely on the fact that we updated the "Selected" prop.
            // But the internal "Last Used" state in the child component won't update unless we force it.
            window.location.reload(); // Simplest fix for now given constraints, but let's remove the extra alert causing the "loop" feeling.
        }
    };

    const handleBasalChange = (id) => {
        if (confirm("¿Marcar este punto como el ÚLTIMO utilizado?")) {
            saveInjectionSite('basal', id);
            setSelectedBasal(id);
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

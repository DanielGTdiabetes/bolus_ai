import React, { useState, useEffect } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { Card, Button, Input } from '../components/ui/Atoms';
import { getSettings, updateSettings } from '../lib/api';

export default function LabsPage() {
    const [settings, setSettings] = useState(null);
    const [loading, setLoading] = useState(true);

    const loadSettings = async () => {
        setLoading(true);
        try {
            const data = await getSettings();
            setSettings(data);
        } catch (e) {
            alert("Error cargando Labs: " + e.message);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadSettings();
    }, []);

    const toggleShadow = async () => {
        if (!settings) return;
        const currentVal = settings.labs?.shadow_mode_enabled ?? false;
        const newVal = !currentVal;

        // Update deeply nested structure safely
        const updated = {
            ...settings,
            labs: {
                ...settings.labs,
                shadow_mode_enabled: newVal
            }
        };

        try {
            await updateSettings(updated);
            const fresh = await getSettings();
            setSettings(fresh);
        } catch (e) {
            alert("Error guardando: " + e.message);
        }
    };

    return (
        <>
            <Header title="Laboratorio 🧪" showBack={true} />
            <main className="page" style={{ paddingBottom: '80px' }}>
                <div style={{ marginBottom: '1rem', color: '#64748b', fontSize: '0.9rem', padding: '0 1rem' }}>
                    Funciones experimentales y de aprendizaje automático.
                </div>

                {loading ? (
                    <div className="spinner">Cargando...</div>
                ) : (
                    <div className="stack" style={{ gap: '1rem' }}>

                        {/* SHADOW LABS */}
                        <Card title="🧠 Shadow Labs (Aprendizaje)">
                            <div className="stack">
                                <div style={{ fontSize: '0.9rem', color: '#475569' }}>
                                    El sistema analiza tus decisiones vs resultados reales para aprender qué funciona mejor.
                                </div>
                                <div style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                        <div style={{ fontWeight: 600 }}>Modo Aprendizaje</div>
                                        <div
                                            onClick={toggleShadow}
                                            style={{
                                                width: '40px', height: '20px', borderRadius: '20px',
                                                background: settings?.labs?.shadow_mode_enabled ? '#10b981' : '#cbd5e1',
                                                position: 'relative', cursor: 'pointer', transition: '0.3s'
                                            }}
                                        >
                                            <div style={{
                                                width: '16px', height: '16px', borderRadius: '50%',
                                                background: 'white', position: 'absolute',
                                                top: '2px', left: settings?.labs?.shadow_mode_enabled ? '22px' : '2px',
                                                transition: '0.3s'
                                            }}></div>
                                        </div>
                                    </div>
                                    <div style={{ fontSize: '0.8rem', color: '#64748b', marginTop: '0.5rem' }}>
                                        {settings?.labs?.shadow_mode_enabled ?
                                            "✅ ACTIVO: Analizando correcciones en segundo plano." :
                                            "❌ INACTIVO: Aprendizaje pausado."}
                                    </div>
                                </div>
                            </div>
                        </Card>

                        {/* INFO BOX */}
                        <Card>
                            <div style={{ fontSize: '0.85rem', color: '#64748b', fontStyle: 'italic' }}>
                                ℹ️ Los cambios en "Aplicar Correcciones" solo están disponibles para usuarios expertos en el código fuente por seguridad. El modo automático aplica sugerencias solo si la confianza es &gt; 95%.
                            </div>
                        </Card>

                    </div>
                )}
            </main>
            <BottomNav />
        </>
    );
}

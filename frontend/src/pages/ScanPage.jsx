import React, { useState, useEffect, useRef } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { Card, Button } from '../components/ui/Atoms';
import {
    estimateCarbsFromImage, connectScale, disconnectScale,
    tare, setOnData
} from '../lib/api';
import { state } from '../modules/core/store';
import { navigate } from '../modules/core/router';

export default function ScanPage() {
    // We assume 'state' from store.js is the source of truth for "session" data 
    // like connected scale or current plate.
    // We sync it to local state for rendering.

    const [plateEntries, setPlateEntries] = useState(state.plateBuilder?.entries || []);
    const [scale, setScale] = useState(state.scale || { connected: false, grams: 0, stable: true });

    // Refresh local scale state when global store updates (via callback)
    useEffect(() => {
        const handler = (data) => {
            // Update global
            if (typeof data.grams === 'number') state.scale.grams = data.grams;
            if (typeof data.stable === 'boolean') state.scale.stable = data.stable;
            if (typeof data.connected === 'boolean') state.scale.connected = data.connected;

            // Update local
            setScale({ ...state.scale });
        };

        if (state.scale.connected) {
            setOnData(handler);
        }

        // We also want to capture the handler so we can set it on connect
        window.scaleHandler = handler;

        return () => { setOnData(null); };
    }, []);

    const handlePlateUpdate = (newEntries) => {
        setPlateEntries([...newEntries]);
        state.plateBuilder.entries = newEntries;
        state.plateBuilder.total = newEntries.reduce((sum, e) => sum + e.carbs, 0);
    };

    return (
        <>
            <Header title="Escanear / Pesar" showBack={true} />
            <main className="page" style={{ paddingBottom: '90px' }}>
                <CameraSection
                    scaleGrams={scale.grams}
                    plateEntries={plateEntries}
                    onAddEntry={(entry) => handlePlateUpdate([...plateEntries, entry])}
                />

                <ScaleSection
                    scale={scale}
                    setScale={setScale}
                />

                <PlateBuilder
                    entries={plateEntries}
                    onUpdate={handlePlateUpdate}
                    scaleGrams={scale.grams}
                />
            </main>
            <BottomNav activeTab="scan" />
        </>
    );
}

function CameraSection({ scaleGrams, plateEntries, onAddEntry }) {
    const [analyzing, setAnalyzing] = useState(false);
    const [preview, setPreview] = useState(null);
    const [msg, setMsg] = useState(null);
    const cameraInputRef = useRef(null);
    const galleryInputRef = useRef(null);

    const handleFile = async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;

        // Preview
        const reader = new FileReader();
        reader.onload = (ev) => {
            setPreview(ev.target.result);
            state.currentImageBase64 = ev.target.result; // Store globally if needed
        };
        reader.readAsDataURL(file);

        setAnalyzing(true);
        setMsg(null);

        try {
            const options = {};
            let netWeight = 0;

            // Smart Net Weight: Current Scale Weight - Weight of items already on plate?
            // Simplified: If scale has weight, we assume it's the NEW item if we differ from previous total?
            // Actually original logic: subtract sum of known weights.
            if (scaleGrams > 0) {
                const previousWeight = plateEntries.reduce((sum, e) => sum + (e.weight || 0), 0);
                netWeight = Math.max(0, scaleGrams - previousWeight);
                options.plate_weight_grams = netWeight;
            }

            if (plateEntries.length > 0) {
                options.existing_items = plateEntries.map(e => e.name).join(", ");
            }

            const result = await estimateCarbsFromImage(file, options);

            const entry = {
                carbs: result.carbs_estimate_g,
                weight: netWeight,
                img: state.currentImageBase64,
                name: result.food_name || "Alimento IA"
            };

            onAddEntry(entry);
            setMsg(`✅ Añadido: ${result.carbs_estimate_g}g (${result.food_name || 'Detectado'})`);
            setTimeout(() => setMsg(null), 3000);

        } catch (err) {
            setMsg(`❌ Error: ${err.message}`);
        } finally {
            setAnalyzing(false);
        }
    };

    return (
        <div className="stack">
            {/* Camera Placeholder / Preview */}
            <div
                className="camera-placeholder"
                onClick={() => cameraInputRef.current.click()}
                style={{
                    background: '#f1f5f9', borderRadius: '16px', height: '200px',
                    display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                    border: '2px dashed #cbd5e1', cursor: 'pointer', overflow: 'hidden', position: 'relative'
                }}
            >
                {preview ? (
                    <img src={preview} style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
                ) : (
                    <>
                        <div style={{ fontSize: '3rem' }}>📷</div>
                        <div style={{ color: '#64748b' }}>Toca para tomar foto</div>
                    </>
                )}

                {analyzing && (
                    <div style={{
                        position: 'absolute', inset: 0, background: 'rgba(255,255,255,0.8)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 'bold', color: 'var(--primary)'
                    }}>
                        ⏳ Analizando IA...
                    </div>
                )}
            </div>

            {msg && <div style={{ textAlign: 'center', padding: '0.5rem', background: msg.startsWith('❌') ? '#fee2e2' : '#dcfce7', color: msg.startsWith('❌') ? '#991b1b' : '#166534', borderRadius: '8px' }}>{msg}</div>}

            <div className="vision-actions" style={{ display: 'flex', gap: '0.5rem' }}>
                <Button onClick={() => cameraInputRef.current.click()} style={{ flex: 1 }}>📷 Cámara</Button>
                <Button variant="secondary" onClick={() => galleryInputRef.current.click()} style={{ flex: 1 }}>🖼️ Galería</Button>
            </div>

            <input type="file" ref={cameraInputRef} accept="image/*" capture="environment" hidden onChange={handleFile} />
            <input type="file" ref={galleryInputRef} accept="image/*" hidden onChange={handleFile} />
        </div>
    );
}

function ScaleSection({ scale, setScale }) {
    const handleConnect = async () => {
        if (scale.connected) {
            await disconnectScale();
            setScale(prev => ({ ...prev, connected: false }));
            state.scale.connected = false;
        } else {
            try {
                await connectScale();
                state.scale.connected = true;
                setScale(prev => ({ ...prev, connected: true }));
                if (window.scaleHandler) setOnData(window.scaleHandler);
            } catch (e) {
                alert("Error conectando báscula: " + e.message);
            }
        }
    };

    const handleTare = async () => {
        await tare();
    };

    const handleUseWeight = () => {
        state.tempCarbs = scale.grams;
        navigate('#/bolus');
    };

    return (
        <Card className="scale-card" style={{ marginTop: '1.5rem' }}>
            <h3 style={{ margin: '0 0 1rem 0' }}>⚖️ Báscula Bluetooth</h3>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div className={`status-badge ${scale.connected ? 'success' : ''}`} style={{
                    padding: '0.25rem 0.75rem', borderRadius: '99px', fontSize: '0.75rem', fontWeight: 600,
                    background: scale.connected ? '#dcfce7' : '#f1f5f9', color: scale.connected ? '#166534' : '#64748b'
                }}>
                    {scale.connected ? 'Conectado' : 'Desconectado'}
                </div>
                <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: '2rem', fontWeight: 800, color: 'var(--primary)' }}>
                        {scale.grams !== null ? scale.grams : '--'} <span style={{ fontSize: '1rem' }}>g</span>
                    </div>
                </div>
            </div>

            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '1rem' }}>
                <Button variant="secondary" onClick={handleConnect} style={{ flex: 1 }}>
                    {scale.connected ? 'Desconectar' : 'Conectar'}
                </Button>
                <Button variant="ghost" onClick={handleTare} disabled={!scale.connected}>Tarar</Button>
                <Button onClick={handleUseWeight} disabled={!scale.connected || !scale.grams}>Usar Peso</Button>
            </div>
        </Card>
    );
}

function PlateBuilder({ entries, onUpdate, scaleGrams }) {
    const total = entries.reduce((acc, e) => acc + e.carbs, 0);

    const removeEntry = (idx) => {
        const newEntries = [...entries];
        newEntries.splice(idx, 1);
        onUpdate(newEntries);
    };

    const goToBolus = () => {
        state.tempCarbs = total;
        state.tempReason = "plate_builder";
        navigate('#/bolus');
    };

    return (
        <Card style={{ marginTop: '1.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <h3 style={{ margin: 0 }}>🍽️ Mi Plato</h3>
                <span style={{ fontWeight: 700, color: 'var(--primary)' }}>{Math.round(total)}g  Total</span>
            </div>

            <div style={{ minHeight: '50px', marginBottom: '1rem' }}>
                {entries.length === 0 && <div className="text-muted text-center" style={{ padding: '1rem' }}>Plato vacío</div>}

                {entries.map((entry, idx) => (
                    <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.5rem', borderBottom: '1px solid #eee' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            {entry.img ? (
                                <img src={entry.img} style={{ width: '40px', height: '40px', objectFit: 'cover', borderRadius: '6px' }} />
                            ) : (
                                <span style={{ fontSize: '1.5rem' }}>🥣</span>
                            )}
                            <div>
                                <div style={{ fontWeight: 600 }}>{entry.carbs}g carbs</div>
                                <div style={{ fontSize: '0.7rem', color: '#888' }}>{entry.name} {entry.weight ? `(${entry.weight}g)` : ''}</div>
                            </div>
                        </div>
                        <button onClick={() => removeEntry(idx)} style={{ background: 'none', border: 'none', color: 'red', cursor: 'pointer', padding: '0.5rem' }}>✕</button>
                    </div>
                ))}
            </div>

            {entries.length > 0 && (
                <Button onClick={goToBolus} style={{ width: '100%' }}>🧮 Calcular con Total</Button>
            )}
        </Card>
    );
}

import React, { useState, useEffect, useRef } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { Card, Button } from '../components/ui/Atoms';
import {
    estimateCarbsFromImage, connectScale, disconnectScale,
    tare, setOnData
} from '../lib/api';
import { analyzeMenuImage } from '../lib/restaurantApi';
import { state } from '../modules/core/store';
import { navigate } from '../modules/core/router';
import { RESTAURANT_MODE_ENABLED } from '../lib/featureFlags';
import { RestaurantSession } from '../components/restaurant/RestaurantSession';

export default function ScanPage() {
    // We assume 'state' from store.js is the source of truth for "session" data 
    // like connected scale or current plate.
    // We sync it to local state for rendering.

    const [plateEntries, setPlateEntries] = useState(state.plateBuilder?.entries || []);
    const [scale, setScale] = useState(state.scale || { connected: false, grams: 0, stable: true });
    const [useSimpleMode, setUseSimpleMode] = useState(!RESTAURANT_MODE_ENABLED);
    const [scanMode, setScanMode] = useState('plate'); // Lifted state

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

    const handleStartSession = () => {
        if (plateEntries.length === 0) {
            alert('⚠️ Añade al menos un plato de la carta primero.');
            return;
        }

        const totalCarbs = plateEntries.reduce((s, e) => s + (e.carbs || 0), 0);
        const totalFat = plateEntries.reduce((s, e) => s + (e.fat || 0), 0);
        const totalProt = plateEntries.reduce((s, e) => s + (e.protein || 0), 0);

        state.tempCarbs = totalCarbs;
        state.tempFat = totalFat;
        state.tempProtein = totalProt;
        state.tempItems = plateEntries.map(e => e.name);
        state.tempReason = "restaurant_kickoff";

        // Mark for BolusPage to start session
        state.tempRestaurantSession = {
            expectedCarbs: totalCarbs,
            expectedFat: totalFat,
            expectedProtein: totalProt,
            expectedItems: plateEntries,
            confidence: state.lastMenuResult?.confidence || 0.5,
            rawMenuResult: state.lastMenuResult
        };

        navigate('#/bolus');
    };

    const showRestaurantFlow = RESTAURANT_MODE_ENABLED && !useSimpleMode;
    const headerTitle = showRestaurantFlow ? 'Sesión restaurante' : 'Escanear / Pesar';

    return (
        <>
            <Header title={headerTitle} showBack={true} />
            <main className="page" style={{ paddingBottom: '90px' }}>
                {showRestaurantFlow ? (
                    <div className="stack" style={{ gap: '1rem' }}>
                        <div style={{ color: '#475569' }}>
                            <strong>Sesión restaurante</strong>: empieza escaneando la carta y añade platos reales. La cámara se abre directamente.
                        </div>
                        <RestaurantSession />
                        <Button variant="ghost" onClick={() => setUseSimpleMode(true)} style={{ alignSelf: 'flex-start' }}>
                            Usar modo simple
                        </Button>
                    </div>
                ) : (
                    <>
                        {RESTAURANT_MODE_ENABLED && (
                            <div style={{ marginBottom: '1rem' }}>
                                <Button variant="secondary" onClick={() => setUseSimpleMode(false)}>
                                    Volver a sesión restaurante
                                </Button>
                            </div>
                        )}
                        <CameraSection
                            scaleGrams={scale.grams}
                            plateEntries={plateEntries}
                            onAddEntry={(entry) => handlePlateUpdate([...plateEntries, entry])}
                            scanMode={scanMode}
                            setScanMode={setScanMode}
                        />

                        <ScaleSection
                            scale={scale}
                            setScale={setScale}
                        />

                        <PlateBuilder
                            entries={plateEntries}
                            onUpdate={handlePlateUpdate}
                            scaleGrams={scale.grams}
                            scanMode={scanMode}
                            onStartSession={handleStartSession}
                        />
                    </>
                )}
            </main>
            <BottomNav activeTab="scan" />
        </>
    );
}

function CameraSection({ scaleGrams, plateEntries, onAddEntry, scanMode, setScanMode }) {
    const [analyzing, setAnalyzing] = useState(false);
    const [preview, setPreview] = useState(null);
    const [msg, setMsg] = useState(null);
    const cameraInputRef = useRef(null);
    const galleryInputRef = useRef(null);

    // Removed local scanMode state
    const [detectedItems, setDetectedItems] = useState([]); // For menu mode

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
        setDetectedItems([]); // Clear previous menu items

        try {
            const options = {};
            let netWeight = 0;

            // Start Analysis
            let result;

            if (scanMode === 'menu') {
                // Specialized Menu Analysis
                result = await analyzeMenuImage(file);
                // Standardize keys for existing UI if needed, but we mostly use result.items
                // Store full result globally for "Restaurant Session" start
                state.lastMenuResult = result;

                if (result.items && result.items.length > 0) {
                    setDetectedItems(result.items);
                    setMsg('👇 Selecciona los platos que vas a pedir');
                } else {
                    setMsg('⚠️ No se detectaron platos claros en la carta');
                }
            } else {
                // Standard Plate Analysis
                if (scaleGrams > 0) {
                    const previousWeight = plateEntries.reduce((sum, e) => sum + (e.weight || 0), 0);
                    netWeight = Math.max(0, scaleGrams - previousWeight);
                    options.plate_weight_grams = netWeight;
                }

                if (plateEntries.length > 0) {
                    options.existing_items = plateEntries.map(e => e.name).join(", ");
                }

                result = await estimateCarbsFromImage(file, options);
            }

            // Calculate total fat/protein from items if available
            const totalFat = (result.items || []).reduce((sum, i) => sum + (i.fat_g || 0), 0);
            const totalProt = (result.items || []).reduce((sum, i) => sum + (i.protein_g || 0), 0);

            if (scanMode === 'plate') {
                // AUTO ADD (Classic Behavior)
                const entry = {
                    carbs: result.carbs_estimate_g,
                    weight: netWeight,
                    fat: totalFat,
                    protein: totalProt,
                    img: state.currentImageBase64,
                    name: result.food_name || "Alimento IA"
                };

                onAddEntry(entry);

                if (result.learning_hint) {
                    state.tempLearningHint = result.learning_hint; // Persist hint for BolusPage
                }

                let msgText = `✅ Añadido: ${result.carbs_estimate_g}g`;
                if (totalFat > 5 || totalProt > 5) {
                    msgText += ` (G:${Math.round(totalFat)}, P:${Math.round(totalProt)})`;
                }
                if (result.bolus && result.bolus.kind === 'extended') {
                    msgText += " 💡 Sugiere Dual";
                }
                else if (result.learning_hint && result.learning_hint.suggest_extended) {
                    msgText += " 🧠 Memoria Sugiere Dual";
                }

                setMsg(msgText);
                setTimeout(() => setMsg(null), 3000);

            } else {
                // Already handled in menu block above
            }

        } catch (err) {
            setMsg(`❌ Error: ${err.message}`);
        } finally {
            setAnalyzing(false);
        }
    };

    const addToPlateFromMenu = (item) => {
        onAddEntry({
            carbs: item.carbs_g,
            fat: item.fat_g || 0,
            protein: item.protein_g || 0,
            name: item.name,
            img: null // No specific img for sub-item crop yet
        });
        setMsg(`✅ Añadido: ${item.name}`);
        setTimeout(() => setMsg(null), 2000);
    };

    const startRestaurantSession = () => {
        if (plateEntries.length === 0) {
            setMsg('⚠️ Añade al menos un plato de la carta primero.');
            return;
        }

        const totalCarbs = plateEntries.reduce((s, e) => s + (e.carbs || 0), 0);
        const totalFat = plateEntries.reduce((s, e) => s + (e.fat || 0), 0);
        const totalProt = plateEntries.reduce((s, e) => s + (e.protein || 0), 0);

        state.tempCarbs = totalCarbs;
        state.tempFat = totalFat;
        state.tempProtein = totalProt;
        state.tempItems = plateEntries.map(e => e.name);
        state.tempReason = "restaurant_kickoff";

        // Mark for BolusPage to start session
        state.tempRestaurantSession = {
            expectedCarbs: totalCarbs,
            expectedFat: totalFat,
            expectedProtein: totalProt,
            expectedItems: plateEntries, // Store full details
            confidence: state.lastMenuResult?.confidence || 0.5,
            rawMenuResult: state.lastMenuResult
        };

        navigate('#/bolus');
    };

    return (
        <div className="stack">
            {/* Mode Switcher */}
            <div style={{ display: 'flex', background: '#e2e8f0', padding: '6px', borderRadius: '16px', marginBottom: '1.5rem', gap: '6px' }}>
                <button
                    onClick={() => setScanMode('plate')}
                    style={{
                        flex: 1, padding: '12px', borderRadius: '12px', border: 'none',
                        background: scanMode === 'plate' ? '#fff' : 'transparent',
                        color: scanMode === 'plate' ? 'var(--primary)' : '#64748b',
                        fontWeight: scanMode === 'plate' ? 800 : 500,
                        boxShadow: scanMode === 'plate' ? '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)' : 'none',
                        transition: 'all 0.2s ease',
                        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', fontSize: '1rem'
                    }}>
                    <span style={{ fontSize: '1.4rem' }}>🍽️</span> Un Plato
                </button>
                <button
                    onClick={() => setScanMode('menu')}
                    style={{
                        flex: 1, padding: '12px', borderRadius: '12px', border: 'none',
                        background: scanMode === 'menu' ? '#fff' : 'transparent',
                        color: scanMode === 'menu' ? 'var(--primary)' : '#64748b',
                        fontWeight: scanMode === 'menu' ? 800 : 500,
                        boxShadow: scanMode === 'menu' ? '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)' : 'none',
                        transition: 'all 0.2s ease',
                        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', fontSize: '1rem'
                    }}>
                    <span style={{ fontSize: '1.4rem' }}>📜</span> Carta
                </button>
            </div>

            {RESTAURANT_MODE_ENABLED && scanMode === 'menu' && (
                <div style={{ marginBottom: '0.75rem' }}>
                    <Button onClick={() => navigate('#/restaurant')} style={{ width: '100%' }}>
                        Sesión restaurante
                    </Button>
                </div>
            )}

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

            {msg && <div style={{ textAlign: 'center', padding: '0.5rem', marginTop: '0.5rem', background: msg.startsWith('❌') ? '#fee2e2' : '#dcfce7', color: msg.startsWith('❌') ? '#991b1b' : '#166534', borderRadius: '8px' }}>{msg}</div>}

            {/* Menu Detected Items List */}
            {scanMode === 'menu' && detectedItems.length > 0 && (
                <div className="menu-results" style={{ marginTop: '1rem', border: '1px solid #e2e8f0', borderRadius: '12px', overflow: 'hidden' }}>
                    <div style={{ background: '#f8fafc', padding: '0.5rem 1rem', borderBottom: '1px solid #e2e8f0', fontWeight: 600, color: '#475569' }}>Platos Detectados</div>
                    {detectedItems.map((item, idx) => (
                        <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.75rem 1rem', borderBottom: '1px solid #f1f5f9' }}>
                            <div style={{ flex: 1 }}>
                                <div style={{ fontWeight: 600 }}>{item.name}</div>
                                <div style={{ fontSize: '0.8rem', color: '#64748b' }}>~{item.carbs_g}g carbs</div>
                            </div>
                            <Button size="sm" onClick={() => addToPlateFromMenu(item)} style={{ padding: '0.4rem 0.8rem' }}>+ Añadir</Button>
                        </div>
                    ))}
                </div>
            )}

            <div className="vision-actions" style={{ display: 'flex', gap: '0.5rem', marginTop: '1rem' }}>
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

function PlateBuilder({ entries, onUpdate, scaleGrams, scanMode, onStartSession }) {
    const total = entries.reduce((acc, e) => acc + e.carbs, 0);

    const removeEntry = (idx) => {
        const newEntries = [...entries];
        newEntries.splice(idx, 1);
        onUpdate(newEntries);
    };

    const goToBolus = () => {
        if (scanMode === 'menu' && onStartSession) {
            onStartSession();
            return;
        }
        state.tempCarbs = total;
        state.tempFat = entries.reduce((acc, e) => acc + (e.fat || 0), 0);
        state.tempProtein = entries.reduce((acc, e) => acc + (e.protein || 0), 0);
        state.tempItems = entries.map(e => e.name);
        state.tempReason = "plate_builder";
        navigate('#/bolus');
    };

    const actionLabel = (scanMode === 'menu') ? '🚀 Iniciar Comida Restaurante' : '🧮 Calcular con Total';

    return (
        <Card style={{ marginTop: '1.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <h3 style={{ margin: 0 }}>🍽️ Mi Plato {scanMode === 'menu' ? '(Carta)' : ''}</h3>
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
                <Button onClick={goToBolus} style={{ width: '100%', background: scanMode === 'menu' ? 'var(--primary)' : undefined }}>
                    {actionLabel}
                </Button>
            )}
        </Card>
    );
}

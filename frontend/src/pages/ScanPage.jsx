import React, { useState, useEffect, useRef } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { Card, Button } from '../components/ui/Atoms';
import { estimateCarbsFromImage } from '../lib/api';
import { analyzeMenuImage } from '../lib/restaurantApi';
import { state } from '../modules/core/store';
import { navigate } from '../modules/core/navigation';
import { RESTAURANT_MODE_ENABLED } from '../lib/featureFlags';
import { RestaurantSession } from '../components/restaurant/RestaurantSession';
import { ScaleSection as ScaleControl } from '../components/scale/ScaleSection';

export default function ScanPage() {
    // We assume 'state' from store.js is the source of truth for "session" data 
    // like connected scale or current plate.
    // We sync it to local state for rendering.

    const [plateEntries, setPlateEntries] = useState(state.plateBuilder?.entries || []);
    const [scale, setScale] = useState(state.scale || { connected: false, grams: 0, stable: true });
    const [useSimpleMode, setUseSimpleMode] = useState(true);
    const [scanMode, setScanMode] = useState('plate'); // Lifted state


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
        state.tempReason = "restaurant_menu";

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

    const showRestaurantFlow = !useSimpleMode;
    const headerTitle = showRestaurantFlow ? 'Sesión restaurante' : 'Escanear / Pesar';

    const handlePlateUpdate = (newEntries) => {
        setPlateEntries(newEntries);
        state.plateBuilder = { entries: newEntries };
    };

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

                        {RESTAURANT_MODE_ENABLED && (() => {
                            try {
                                const raw = localStorage.getItem('restaurant_session_v1');
                                if (!raw) return false;
                                const data = JSON.parse(raw);
                                // Session is only active if it has expectedCarbs (menu scanned/entered) and isn't finalized
                                return data.expectedCarbs && !data.finalizedAt;
                            } catch { return false; }
                        })() && (
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

                        {scanMode !== 'menu' && (
                            <>
                                <ScaleControl onDataReceived={() => setScale({ ...state.scale })} />

                                <PlateBuilder
                                    entries={plateEntries}
                                    onUpdate={handlePlateUpdate}
                                    scaleGrams={scale.grams}
                                    scanMode={scanMode}
                                    onStartSession={handleStartSession}
                                />
                            </>
                        )}
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
    const requestIdRef = useRef(0);
    const abortRef = useRef(null);

    const [imageDescription, setImageDescription] = useState('');

    // Removed local scanMode state
    const [detectedItems, setDetectedItems] = useState([]); // For menu mode
    const MAX_IMAGE_MB = 6;
    const allowedTypes = ["image/jpeg", "image/png", "image/webp"];

    const abortInFlight = () => {
        if (abortRef.current) {
            abortRef.current.abort();
            abortRef.current = null;
        }
    };

    const beginRequest = () => {
        abortInFlight();
        const requestId = requestIdRef.current + 1;
        requestIdRef.current = requestId;
        const controller = new AbortController();
        abortRef.current = controller;
        return { requestId, controller };
    };

    const cancelCurrent = () => {
        const cancelId = requestIdRef.current;
        abortInFlight();
        requestIdRef.current = cancelId + 1;
        setAnalyzing(false);
        setMsg('⏹️ Análisis cancelado.');
    };

    useEffect(() => {
        return () => abortInFlight();
    }, []);

    const handleFile = async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        e.target.value = '';
        if (file.type && !allowedTypes.includes(file.type)) {
            setMsg('⚠️ Formato no compatible. Usa JPG, PNG o WEBP.');
            return;
        }
        if (file.size > MAX_IMAGE_MB * 1024 * 1024) {
            setMsg(`⚠️ Imagen demasiado grande (máx ${MAX_IMAGE_MB}MB).`);
            return;
        }

        // Preview
        const reader = new FileReader();
        reader.onload = (ev) => {
            setPreview(ev.target.result);
            state.currentImageBase64 = ev.target.result; // Store globally if needed
        };
        reader.readAsDataURL(file);

        const { requestId, controller } = beginRequest();

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
                result = await analyzeMenuImage(file, { signal: controller.signal });
                // Standardize keys for existing UI if needed, but we mostly use result.items
                // Store full result globally for "Restaurant Session" start
                state.lastMenuResult = result;

                if (requestId !== requestIdRef.current) return;
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

                if (imageDescription.trim()) {
                    options.image_description = imageDescription.trim();
                }

                result = await estimateCarbsFromImage(file, { ...options, signal: controller.signal });
            }

            if (requestId !== requestIdRef.current) return;
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
                const cautionNotes = [];
                if (result.confidence === 'low') {
                    cautionNotes.push('baja confianza');
                }
                if (result.needs_user_input && result.needs_user_input.length > 0) {
                    cautionNotes.push(result.needs_user_input[0].question);
                }
                if (totalFat > 5 || totalProt > 5) {
                    msgText += ` (G:${Math.round(totalFat)}, P:${Math.round(totalProt)})`;
                }
                if (result.bolus && result.bolus.kind === 'extended') {
                    state.tempBolusKind = result.bolus.kind;
                    msgText += " 💡 Sugiere Dual";
                }
                else if (result.learning_hint && result.learning_hint.suggest_extended) {
                    msgText += " 🧠 Memoria Sugiere Dual";
                }
                if (cautionNotes.length > 0) {
                    msgText = `⚠️ ${msgText} · ${cautionNotes.join(" / ")}`;
                }

                setMsg(msgText);
                setTimeout(() => setMsg(null), 3000);

            } else {
                // Already handled in menu block above
            }

        } catch (err) {
            if (requestId !== requestIdRef.current) return;
            if (err?.name === 'AbortError') {
                setMsg('⏹️ Análisis cancelado.');
            } else {
                setMsg(`❌ Error: ${err.message}`);
            }
        } finally {
            if (requestId === requestIdRef.current) {
                setAnalyzing(false);
                abortRef.current = null;
            }
            // Optional: clear description after success? Maybe user wants to keep it if it failed?
            // Keeping it for now.
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
        state.tempReason = "restaurant_menu";

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

            {/* Show specific UI based on mode */}
            {scanMode === 'menu' ? (
                <div style={{ marginTop: '2rem', textAlign: 'center' }}>
                    <div style={{ fontSize: '4rem', marginBottom: '1rem' }}>🧑‍🍳</div>
                    <p style={{ color: '#475569', marginBottom: '1.5rem', lineHeight: '1.5' }}>
                        El modo <strong>Carta</strong> activa el flujo completo de restaurante:
                        <br />
                        1. Escanea o describe el menú
                        <br />
                        2. Planifica tu comida
                        <br />
                        3. Añade platos reales
                    </p>
                    <Button onClick={() => setUseSimpleMode(false)} style={{ width: '100%', padding: '1rem', fontSize: '1.1rem', background: 'var(--primary)', color: 'white', fontWeight: 'bold', boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1)' }}>
                        📸 Escanear Menú y Comenzar
                    </Button>
                </div>
            ) : (
                <>
                    {/* Camera Placeholder / Preview for Plate Mode */}
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

                    <div style={{ marginTop: '1rem' }}>
                        <label style={{ display: 'block', marginBottom: '0.25rem', color: '#475569', fontWeight: 600 }}>
                            📝 Descripción adicional (opcional)
                        </label>
                        <textarea
                            rows={2}
                            placeholder="Ej: Una cuchara de crema de cacahuete, sin azúcar..."
                            value={imageDescription}
                            onChange={(e) => setImageDescription(e.target.value)}
                            style={{
                                width: '100%', padding: '0.75rem', borderRadius: '8px', border: '1px solid #cbd5e1',
                                fontFamily: 'inherit', resize: 'vertical'
                            }}
                        />
                    </div>

                    {msg && (
                        <div
                            style={{
                                textAlign: 'center',
                                padding: '0.5rem',
                                marginTop: '0.5rem',
                                background: msg.startsWith('❌') ? '#fee2e2' : msg.startsWith('⚠️') || msg.startsWith('⏹️') ? '#fef3c7' : '#dcfce7',
                                color: msg.startsWith('❌') ? '#991b1b' : msg.startsWith('⚠️') || msg.startsWith('⏹️') ? '#92400e' : '#166534',
                                borderRadius: '8px'
                            }}
                        >
                            {msg}
                        </div>
                    )}

                    <div className="vision-actions" style={{ display: 'flex', gap: '0.5rem', marginTop: '1rem' }}>
                        <Button onClick={() => cameraInputRef.current.click()} style={{ flex: 1 }} disabled={analyzing}>📷 Cámara</Button>
                        <Button variant="secondary" onClick={() => galleryInputRef.current.click()} style={{ flex: 1 }} disabled={analyzing}>🖼️ Galería</Button>
                        {analyzing && (
                            <Button
                                variant="ghost"
                                onClick={() => {
                                    cancelCurrent();
                                }}
                                style={{ flex: 1 }}
                            >
                                Cancelar
                            </Button>
                        )}
                    </div>

                    {/* Manual test: Start scan A, cancel; start scan B immediately; confirm UI stays analyzing B without showing canceled from A. */}

                    <input type="file" ref={cameraInputRef} accept="image/*" capture="environment" hidden onChange={handleFile} />
                    <input type="file" ref={galleryInputRef} accept="image/*" hidden onChange={handleFile} />
                </>
            )}
        </div>
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

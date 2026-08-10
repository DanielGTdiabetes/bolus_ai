import React, { useEffect, useRef, useState } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { Card, Button } from '../components/ui/Atoms';
import { estimateCarbsFromImage } from '../lib/api';
import { state } from '../modules/core/store';
import { navigate } from '../modules/core/navigation';
import { ScaleSection as ScaleControl } from '../components/scale/ScaleSection';

export default function ScanPage() {
    const [plateEntries, setPlateEntries] = useState(state.plateBuilder?.entries || []);
    const [scale, setScale] = useState(state.scale || { connected: false, grams: 0, stable: true });

    const handlePlateUpdate = (entries) => {
        setPlateEntries(entries);
        state.plateBuilder = { entries };
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
                <ScaleControl onDataReceived={() => setScale({ ...state.scale })} />
                <PlateBuilder entries={plateEntries} onUpdate={handlePlateUpdate} />
            </main>
            <BottomNav activeTab="scan" />
        </>
    );
}

function CameraSection({ scaleGrams, plateEntries, onAddEntry }) {
    const [analyzing, setAnalyzing] = useState(false);
    const [preview, setPreview] = useState(null);
    const [msg, setMsg] = useState(null);
    const [imageDescription, setImageDescription] = useState('');
    const cameraInputRef = useRef(null);
    const galleryInputRef = useRef(null);
    const requestIdRef = useRef(0);
    const abortRef = useRef(null);
    const allowedTypes = ['image/jpeg', 'image/png', 'image/webp'];

    const abortInFlight = () => {
        abortRef.current?.abort();
        abortRef.current = null;
    };

    useEffect(() => () => abortInFlight(), []);

    const cancelCurrent = () => {
        abortInFlight();
        requestIdRef.current += 1;
        setAnalyzing(false);
        setMsg('Análisis cancelado.');
    };

    const handleFile = async (event) => {
        const file = event.target.files?.[0];
        if (!file) return;
        event.target.value = '';
        if (file.type && !allowedTypes.includes(file.type)) {
            setMsg('Formato no compatible. Usa JPG, PNG o WEBP.');
            return;
        }
        if (file.size > 6 * 1024 * 1024) {
            setMsg('Imagen demasiado grande (máximo 6 MB).');
            return;
        }

        const reader = new FileReader();
        reader.onload = ({ target }) => {
            setPreview(target.result);
            state.currentImageBase64 = target.result;
        };
        reader.readAsDataURL(file);

        abortInFlight();
        const requestId = requestIdRef.current + 1;
        requestIdRef.current = requestId;
        const controller = new AbortController();
        abortRef.current = controller;
        setAnalyzing(true);
        setMsg(null);

        try {
            const previousWeight = plateEntries.reduce((sum, entry) => sum + (entry.weight || 0), 0);
            const netWeight = scaleGrams > 0 ? Math.max(0, scaleGrams - previousWeight) : 0;
            const options = {
                ...(netWeight ? { plate_weight_grams: netWeight } : {}),
                ...(plateEntries.length
                    ? { existing_items: plateEntries.map((entry) => entry.name).join(', ') }
                    : {}),
                ...(imageDescription.trim() ? { image_description: imageDescription.trim() } : {}),
                signal: controller.signal,
            };
            const result = await estimateCarbsFromImage(file, options);
            if (requestId !== requestIdRef.current) return;

            const totalFat = (result.items || []).reduce((sum, item) => sum + (item.fat_g || 0), 0);
            const totalProtein = (result.items || []).reduce((sum, item) => sum + (item.protein_g || 0), 0);
            onAddEntry({
                carbs: result.carbs_estimate_g,
                carbsRange: result.carbs_range_g,
                weight: netWeight,
                fat: totalFat,
                protein: totalProtein,
                img: state.currentImageBase64,
                name: result.food_name || 'Alimento IA',
                visionReference: result.reference_type || 'none',
                visionConfidence: result.confidence,
            });
            if (result.learning_hint) state.tempLearningHint = result.learning_hint;
            if (result.bolus?.kind === 'extended') state.tempBolusKind = result.bolus.kind;
            setMsg(`Añadido: ${result.carbs_estimate_g} g HC`);
        } catch (error) {
            if (requestId !== requestIdRef.current) return;
            setMsg(error?.name === 'AbortError' ? 'Análisis cancelado.' : `Error: ${error.message}`);
        } finally {
            if (requestId === requestIdRef.current) {
                setAnalyzing(false);
                abortRef.current = null;
            }
        }
    };

    return (
        <div className="stack">
            <div
                className="camera-placeholder"
                onClick={() => cameraInputRef.current.click()}
                style={{
                    background: '#f1f5f9', borderRadius: '16px', height: '200px',
                    display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                    border: '2px dashed #cbd5e1', cursor: 'pointer', overflow: 'hidden', position: 'relative'
                }}
            >
                {preview
                    ? <img src={preview} alt="Plato" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
                    : <><div style={{ fontSize: '3rem' }}>📷</div><div style={{ color: '#64748b' }}>Toca para tomar foto</div></>}
                {analyzing && (
                    <div style={{ position: 'absolute', inset: 0, background: 'rgba(255,255,255,0.8)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 'bold', color: 'var(--primary)' }}>
                        Analizando IA…
                    </div>
                )}
            </div>
            <label style={{ color: '#475569', fontWeight: 600 }}>
                Descripción adicional (opcional)
                <textarea
                    rows={2}
                    value={imageDescription}
                    onChange={(event) => setImageDescription(event.target.value)}
                    placeholder="Ej.: una cucharada de crema de cacahuete, sin azúcar…"
                    style={{ width: '100%', marginTop: '0.25rem', padding: '0.75rem', borderRadius: '8px', border: '1px solid #cbd5e1', fontFamily: 'inherit', resize: 'vertical' }}
                />
            </label>
            {msg && <div style={{ textAlign: 'center', padding: '0.5rem' }}>{msg}</div>}
            <div style={{ display: 'flex', gap: '0.5rem' }}>
                <Button onClick={() => cameraInputRef.current.click()} style={{ flex: 1 }} disabled={analyzing}>Cámara</Button>
                <Button variant="secondary" onClick={() => galleryInputRef.current.click()} style={{ flex: 1 }} disabled={analyzing}>Galería</Button>
                {analyzing && <Button variant="ghost" onClick={cancelCurrent}>Cancelar</Button>}
            </div>
            <input type="file" ref={cameraInputRef} accept="image/*" capture="environment" hidden onChange={handleFile} />
            <input type="file" ref={galleryInputRef} accept="image/*" hidden onChange={handleFile} />
        </div>
    );
}

function PlateBuilder({ entries, onUpdate }) {
    const total = entries.reduce((sum, entry) => sum + entry.carbs, 0);
    const goToBolus = () => {
        state.tempCarbs = total;
        state.tempFat = entries.reduce((sum, entry) => sum + (entry.fat || 0), 0);
        state.tempProtein = entries.reduce((sum, entry) => sum + (entry.protein || 0), 0);
        state.tempItems = entries.map((entry) => entry.name);
        state.tempReason = 'plate_builder';
        navigate('#/bolus');
    };

    return (
        <Card style={{ marginTop: '1.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1rem' }}>
                <h3 style={{ margin: 0 }}>Mi plato</h3>
                <strong>{Math.round(total)} g HC</strong>
            </div>
            {entries.length === 0 && <div className="text-muted text-center">Plato vacío</div>}
            {entries.map((entry, index) => (
                <div key={`${entry.name}-${index}`} style={{ display: 'flex', justifyContent: 'space-between', padding: '0.5rem', borderBottom: '1px solid #eee' }}>
                    <div><strong>{entry.carbs} g HC</strong><div style={{ fontSize: '0.75rem', color: '#888' }}>{entry.name}</div></div>
                    <button onClick={() => onUpdate(entries.filter((_, itemIndex) => itemIndex !== index))} style={{ background: 'none', border: 'none', color: 'red' }}>×</button>
                </div>
            ))}
            {entries.length > 0 && <Button onClick={goToBolus} style={{ width: '100%', marginTop: '1rem' }}>Calcular con total</Button>}
        </Card>
    );
}

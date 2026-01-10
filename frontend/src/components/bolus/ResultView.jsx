
import React, { useState, useEffect, useMemo } from 'react';
import { Button } from '../ui/Atoms';
import { MainGlucoseChart } from '../charts/MainGlucoseChart';
import { InjectionSiteSelector } from '../injection/InjectionSiteSelector';
import { PreBolusTimer } from './PreBolusTimer';
import { useBolusSimulator } from '../../hooks/useBolusSimulator';
import { addFavorite } from '../../lib/api';

/**
 * ResultView Component
 * Displays the calculation result, simulation graph, and confirmation controls.
 */
export function ResultView({
    result,
    slot,
    settings,
    usedParams,
    onBack,
    onSave,
    saving,
    currentCarbs,
    foodName,
    favorites,
    onFavoriteAdded,
    alcoholEnabled,
    onApplyAutosens,
    carbProfile,
    nsConfig
}) {
    // Local state for edit before confirm
    const [finalDose, setFinalDose] = useState(result.upfront_u);
    const [injectionSite, setInjectionSite] = useState(null);

    // Check if entered food is new
    const [isNewFav, setIsNewFav] = useState(false);
    const [saveFav, setSaveFav] = useState(false);

    // Hook for simulation
    const { predictionData, simulating, runSimulation } = useBolusSimulator();

    // SAFETY CHECK FOR ALCOHOL SIMPLE BOLUS
    const showAlcoholWarning = alcoholEnabled && result.kind === 'normal';

    useEffect(() => {
        if (foodName && foodName.trim().length > 2) {
            const exists = favorites.some(f => f.name.toLowerCase() === foodName.toLowerCase());
            if (!exists) {
                setIsNewFav(true);
                setSaveFav(true);
            }
        }
    }, [foodName, favorites]);

    // Extract Autosens Suggestion if present
    const autosensLine = (result.explain || result.calc?.explain)?.find(l => l.includes('Autosens (Consejo)'));
    let suggestedRatio = null;
    let suggestedMsg = null;

    if (autosensLine) {
        // Regex to find "Factor 1.09" or similar
        const match = autosensLine.match(/Factor\s+(\d+(\.\d+)?)/);
        if (match) {
            suggestedRatio = parseFloat(match[1]);
            suggestedMsg = autosensLine;
        }
    }

    const resolvedParams = useMemo(
        () => usedParams || result?.calc?.used_params || result?.used_params || result?.usedParams,
        [usedParams, result]
    );
    const later = parseFloat(result.later_u || 0);
    const upfront = parseFloat(finalDose || 0);
    const total = upfront + later;

    // Auto-Simulation Debounced
    useEffect(() => {
        if (!resolvedParams) return;
        const timer = setTimeout(() => {
            const dose = parseFloat(finalDose);
            if (!isNaN(dose) && dose >= 0) {
                runSimulation({
                    doseNow: dose,
                    doseLater: later,
                    carbsVal: parseFloat(currentCarbs),
                    params: resolvedParams,
                    slot,
                    carbProfile,
                    dessertMode: false, // Could be passed in props if needed
                    result,
                    nsConfig,
                    settingsAbsorption: settings?.absorption
                });
            }
        }, 800);
        return () => clearTimeout(timer);
    }, [finalDose, resolvedParams, currentCarbs, later, slot, carbProfile, result, nsConfig, settings, runSimulation]);

    const handleConfirm = async () => {
        if (saveFav && isNewFav && foodName) {
            try {
                // Save to API
                const newFav = await addFavorite(foodName, parseFloat(currentCarbs));
                if (onFavoriteAdded) onFavoriteAdded(newFav);
            } catch (err) {
                console.error("Error saving favorite:", err);
                alert("No se pudo guardar el favorito, pero el bolo continuará.");
            }
        }
        onSave(finalDose, injectionSite);
    };

    return (
        <div className="card result-card fade-in" style={{ border: '2px solid var(--primary)', padding: '1.5rem' }}>
            {showAlcoholWarning && (
                <div style={{
                    background: '#fff7ed', border: '1px solid #fdba74', borderRadius: '12px',
                    padding: '1rem', marginBottom: '1rem', display: 'flex', gap: '10px'
                }}>
                    <div style={{ fontSize: '1.5rem' }}>🍷💡</div>
                    <div>
                        <div style={{ fontWeight: 700, color: '#c2410c' }}>Sugerencia: Usa Bolo Dividido</div>
                        <div style={{ fontSize: '0.85rem', color: '#ea580c', marginTop: '4px' }}>
                            Con alcohol, lo más seguro es <strong>dividir la dosis</strong> (menos insulina ahora, más luego).
                            <br />
                            Si prefieres bolo simple, <strong>espera 30 min</strong> antes de inyectar.
                        </div>
                    </div>
                </div>
            )}

            <div style={{ textAlign: 'center' }}>
                <div className="text-muted" style={{ marginBottom: '0.5rem' }}>Bolo Recomendado</div>

                {/* DUAL BOLUS: Prominent Total Display */}
                {result.kind === 'dual' && (
                    <div style={{
                        background: '#f1f5f9',
                        borderRadius: '12px',
                        padding: '1rem',
                        marginBottom: '1.5rem',
                        border: '1px solid #cbd5e1'
                    }}>
                        <div style={{ fontSize: '0.85rem', fontWeight: 700, color: '#64748b', letterSpacing: '1px' }}>TOTAL</div>
                        <div style={{ fontSize: '3rem', fontWeight: 800, color: '#0f172a', lineHeight: 1 }}>
                            {total % 1 === 0 ? total : total.toFixed(2)} <span style={{ fontSize: '1.5rem', color: '#64748b' }}>U</span>
                        </div>
                    </div>
                )}

                {/* Pre-Bolus Timer / Advisory */}
                <PreBolusTimer />

                {resolvedParams && (
                    <div style={{
                        display: 'inline-flex',
                        gap: '8px',
                        alignItems: 'center',
                        background: '#eef2ff',
                        color: '#312e81',
                        padding: '8px 12px',
                        borderRadius: '12px',
                        border: '1px solid #c7d2fe',
                        margin: '0.5rem 0'
                    }}>
                        <span style={{ fontWeight: 700 }}>⚙️ Parámetros usados</span>
                        <span style={{ fontSize: '0.85rem' }}>
                            ICR {resolvedParams.cr_g_per_u}g/U · ISF {resolvedParams.isf_mgdl_per_u} mg/dL/U · DIA {resolvedParams.dia_hours}h · Modelo {resolvedParams.insulin_model || 'linear'}
                        </span>
                    </div>
                )}

                {/* Immediate Input */}
                <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'baseline', gap: '8px' }}>
                    {result.kind === 'dual' && <span style={{ fontSize: '1rem', fontWeight: 600, color: '#64748b' }}>Ahora:</span>}
                    <input
                        type="number"
                        value={finalDose}
                        onChange={e => setFinalDose(e.target.value)}
                        step="0.5"
                        style={{
                            width: '120px', textAlign: 'right',
                            fontSize: result.kind === 'dual' ? '2rem' : '3.5rem',
                            color: 'var(--primary)', fontWeight: 800,
                            border: 'none', borderBottom: '2px dashed var(--primary)',
                            outline: 'none', background: 'transparent'
                        }}
                    />
                    <span style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--primary)' }}>U</span>
                </div>


                {(predictionData || simulating) && (
                    <div className="fade-in" style={{
                        padding: '1rem',
                        marginBottom: '1.5rem',
                        borderRadius: '16px',
                        background: '#f8fafc',
                        border: '1px solid #e2e8f0',
                        display: 'flex', flexDirection: 'column', transition: 'all 0.3s ease'
                    }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1rem' }}>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                <span style={{ fontSize: '0.85rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>
                                    Pronóstico Metabólico {predictionData?.slow_absorption_active ? '🐢' : ''}
                                </span>
                                {!simulating && predictionData?.absorption_profile_used && (
                                    <div style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'flex', gap: '6px', alignItems: 'center' }}>
                                        <span style={{ fontWeight: 600 }}>
                                            {predictionData.absorption_profile_used === 'fast' ? '⚡ Rápida' :
                                                predictionData.absorption_profile_used === 'slow' ? '🍕 Lenta' :
                                                    predictionData.absorption_profile_used === 'med' ? '🥗 Media' : '⚪ Sin carbs'}
                                        </span>
                                        <span style={{
                                            padding: '1px 5px', borderRadius: '4px', fontSize: '0.65rem', fontWeight: 800,
                                            background: predictionData.absorption_confidence === 'high' ? '#dcfce7' : (predictionData.absorption_confidence === 'medium' ? '#fef9c3' : '#fee2e2'),
                                            color: predictionData.absorption_confidence === 'high' ? '#166534' : (predictionData.absorption_confidence === 'medium' ? '#854d0e' : '#991b1b')
                                        }}>
                                            Confianza {predictionData.absorption_confidence === 'high' ? 'Alta' : (predictionData.absorption_confidence === 'medium' ? 'Media' : 'Baja')}
                                        </span>
                                    </div>
                                )}
                            </div>
                            <div style={{ textAlign: 'right' }}>
                                {simulating ? (
                                    <div style={{ fontSize: '0.8rem', color: '#64748b', fontStyle: 'italic' }}>Calculando...</div>
                                ) : (
                                    <>
                                        <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#1e293b' }}>
                                            {Math.round(predictionData.summary.ending_bg)}<span style={{ fontSize: '0.7rem', color: '#64748b', marginLeft: '2px' }}>mg/dL</span>
                                        </div>
                                        <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>En 4 horas</div>
                                    </>
                                )}
                            </div>
                        </div>

                        {/* Chart Area */}
                        <div style={{ height: '160px', width: '100%', position: 'relative', marginBottom: '1rem' }}>
                            {simulating ? (
                                <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                    <div className="pulse-animation" style={{ width: '40px', height: '40px', borderRadius: '50%', background: '#e2e8f0' }}></div>
                                </div>
                            ) : (
                                <MainGlucoseChart
                                    predictionData={predictionData}
                                    height={160}
                                    hideLegend
                                    syncId="bolus-preview"
                                    showTargetBand
                                    targetLow={resolvedParams.target - 20}
                                    targetHigh={resolvedParams.target + 20}
                                />
                            )}
                        </div>

                        {/* Indicators Row */}
                        {!simulating && predictionData && (
                            <div style={{ display: 'flex', justifyContent: 'space-around', alignItems: 'center', width: '100%', borderTop: '1px solid #e2e8f0', paddingTop: '10px' }}>
                                <div style={{ textAlign: "center" }}>
                                    <div style={{ fontSize: "0.65rem", color: "#64748b", textTransform: 'uppercase' }}>Mínimo</div>
                                    <div style={{ fontSize: "1rem", fontWeight: 800, color: predictionData.summary.min_bg < 70 ? '#dc2626' : '#166534' }}>
                                        {Math.round(predictionData.summary.min_bg)}
                                    </div>
                                </div>
                                <div style={{ height: '20px', width: '1px', background: '#cbd5e1' }}></div>
                                <div style={{ textAlign: "center" }}>
                                    <div style={{ fontSize: "0.65rem", color: "#64748b", textTransform: 'uppercase' }}>Máximo</div>
                                    <div style={{ fontSize: "1rem", fontWeight: 800, color: "#1e293b" }}>
                                        {Math.round(predictionData.summary.max_bg)}
                                    </div>
                                </div>
                                <div style={{ height: '20px', width: '1px', background: '#cbd5e1' }}></div>
                                <div style={{ textAlign: "center" }}>
                                    <div style={{ fontSize: "0.65rem", color: "#64748b", textTransform: 'uppercase' }}>Pico en</div>
                                    <div style={{ fontSize: "1rem", fontWeight: 800, color: "#1e293b" }}>
                                        {predictionData.summary.time_to_min}m
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                )}

                {/* Extended Part */}
                {result.kind === 'dual' && (
                    <div style={{ marginTop: '0.5rem', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '5px', color: '#64748b' }}>
                        <span style={{ fontSize: '1rem', fontWeight: 600 }}>Extendido:</span>
                        <span style={{ fontSize: '1.2rem', fontWeight: 700 }}>{result.later_u} U</span>
                        <span style={{ fontSize: '0.9rem' }}>({result.duration_min} min)</span>
                    </div>
                )}
            </div>

            {/* Safety Alerts */}
            {(result.explain || result.calc?.explain)?.filter(l => l.includes('⛔') || l.includes('⚠️')).map((line, i) => (
                <div key={'alert-' + i} style={{
                    background: line.includes('⛔') ? '#fee2e2' : '#fff7ed',
                    color: line.includes('⛔') ? '#991b1b' : '#c2410c',
                    padding: '0.75rem', borderRadius: '8px', marginBottom: '1rem',
                    fontWeight: 'bold', border: line.includes('⛔') ? '2px solid #ef4444' : '1px solid #fdba74'
                }}>
                    {line}
                </div>
            ))}

            <ul style={{ marginTop: '1.5rem', fontSize: '0.85rem', color: '#64748b', paddingLeft: '1.2rem' }}>
                {(result.explain || result.calc?.explain)?.filter(l => !l.includes('⛔') && !l.includes('⚠️')).map((line, i) => <li key={i}>{line}</li>)}
            </ul>

            {result.warnings && result.warnings.length > 0 && (
                <div style={{ background: '#fff7ed', color: '#c2410c', padding: '0.8rem', margin: '1rem 0', borderRadius: '8px', fontSize: '0.85rem', border: '1px solid #fed7aa' }}>
                    <strong>⚠️ Atención:</strong>
                    {result.warnings.map((w, i) => <div key={i}>• {w}</div>)}
                </div>
            )}

            {/* Autosens Suggestion Alert */}
            {autosensLine && suggestedRatio && (
                <div style={{ background: '#eff6ff', color: '#1e40af', padding: '0.8rem', margin: '1rem 0', borderRadius: '8px', fontSize: '0.85rem', border: '1px solid #bfdbfe' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                        <strong>💡 Sugerencia Autosens:</strong>
                        <button onClick={() => {
                            if (onApplyAutosens) onApplyAutosens(suggestedRatio, suggestedMsg);
                        }} style={{
                            background: '#2563eb', color: 'white', border: 'none', borderRadius: '6px',
                            padding: '4px 10px', fontSize: '0.75rem', fontWeight: 'bold', cursor: 'pointer'
                        }}>
                            Aplicar
                        </button>
                    </div>
                    {/* Render the extracted explanation cleanly */}
                    {(result.explain || result.calc?.explain).filter(l => l.includes('Autosens') || l.includes('NO APLICADO')).map((l, i) => (
                        <div key={i} style={{ marginLeft: '10px', marginBottom: '4px' }}>{l.replace('🔍', '').replace('⚠️', '')}</div>
                    ))}
                </div>
            )}

            {isNewFav && (
                <div style={{ margin: '1rem 0', background: '#f0fdf4', padding: '0.8rem', borderRadius: '8px', border: '1px dashed #4ade80' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '0.9rem', color: '#166534', cursor: 'pointer' }}>
                        <input type="checkbox" checked={saveFav} onChange={e => setSaveFav(e.target.checked)} style={{ transform: 'scale(1.2)' }} />
                        <div>
                            <strong>¿Guardar como favorito?</strong>
                            <div style={{ fontSize: '0.8rem', opacity: 0.8 }}>Aprendera que "{foodName}" son {currentCarbs}g.</div>
                        </div>
                    </label>
                </div>
            )}

            <div style={{ margin: '1rem 0' }}>
                <InjectionSiteSelector
                    type="rapid"
                    selected={injectionSite}
                    onSelect={setInjectionSite}
                    autoSelect={true}
                />
            </div>

            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '1.5rem' }}>
                <Button onClick={handleConfirm} disabled={saving} style={{ flex: 1, background: 'var(--success)', padding: '1rem', fontSize: '1.1rem' }}>
                    {saving ? 'Guardando...' : '✅ Confirmar'}
                </Button>
                <Button variant="ghost" onClick={onBack} disabled={saving} style={{ flex: 1 }}>
                    Cancelar
                </Button>
            </div>
        </div>
    );
}

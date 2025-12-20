import React, { useState, useEffect } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { Card, Button, Input } from '../components/ui/Atoms';
import {
    createBasalEntry, createBasalCheckin, runNightScan,
    getBasalAdvice, getBasalTimeline, evaluateBasalChange,
    getLocalNsConfig, getSupplies, updateSupply
} from '../lib/api';
import { InjectionSiteSelector, saveInjectionSite } from '../components/injection/InjectionSiteSelector';

import { BasalGlucoseChart } from '../components/charts/BasalGlucoseChart';

export default function BasalPage() {
    const [refreshTick, setRefreshTick] = useState(0);
    const handleRefresh = () => setRefreshTick(t => t + 1);

    return (
        <>
            <Header title="Asistente Basal" showBack={false} />
            <main className="page" style={{ paddingBottom: '90px' }}>
                <BasalEntrySection onRefresh={handleRefresh} />
                <BasalAdviceSection key={`advice-${refreshTick}`} />
                <BasalGlucoseChart key={`chart-${refreshTick}`} />
                <BasalImpactSection />
                <BasalTimelineSection key={`timeline-${refreshTick}`} />
            </main>
            <BottomNav activeTab="basal" />
        </>
    );
}

function BasalEntrySection({ onRefresh }) {
    const [dose, setDose] = useState('');
    const [date, setDate] = useState(() => {
        const now = new Date();
        const pad = (n) => n < 10 ? '0' + n : n;
        return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
    });
    const [manualBg, setManualBg] = useState('');
    const [showManualBg, setShowManualBg] = useState(false);
    const [msg, setMsg] = useState(null);
    const [loading, setLoading] = useState(false);
    const [injectionSite, setInjectionSite] = useState(null);

    // Late Dose Calculator State
    const [showLateCalc, setShowLateCalc] = useState(false);
    const [usualTime, setUsualTime] = useState('22:00');
    const [usualDose, setUsualDose] = useState('16'); // Default example or load from last history?
    const [calcResult, setCalcResult] = useState(null);

    const saveDose = async (requireDose = true) => {
        const uVal = parseFloat(dose);

        if (requireDose && (isNaN(uVal) || uVal <= 0)) {
            setMsg({ text: "⚠️ Dosis requerida.", type: 'error' });
            return false;
        }

        if (!isNaN(uVal) && uVal > 0) {
            try {
                const dateObj = new Date(date);
                await createBasalEntry({
                    dose_u: uVal,
                    created_at: dateObj.toISOString(),
                    effective_from: dateObj.toISOString().split('T')[0]
                });

                if (injectionSite) {
                    saveInjectionSite('basal', injectionSite);
                }

                // Decrement needle stock (API)
                try {
                    const supplies = await getSupplies();
                    const needles = supplies.find(s => s.key === 'supplies_needles');
                    if (needles && needles.quantity > 0) {
                        await updateSupply('supplies_needles', needles.quantity - 1);
                    }
                } catch (err) {
                    console.warn("Stock update failed", err);
                }

                return true;
            } catch (e) {
                setMsg({ text: "Error guardando dosis: " + e.message, type: 'error' });
                return false;
            }
        }
        return true; // Proceed if not required and empty
    };

    const handleSaveSimple = async () => {
        setLoading(true);
        const ok = await saveDose(true);
        if (ok) {
            setMsg({ text: "✅ Dosis guardada.", type: 'success' });
            setDose(''); // Reset? Or keep?
            if (onRefresh) onRefresh();
        }
        setLoading(false);
    };

    const handleCheckinWake = async () => {
        setLoading(true);
        const ok = await saveDose(false); // Dose optional for checkin
        if (!ok) { setLoading(false); return; }

        setMsg({ text: "Consultando Nightscout...", type: 'info' });

        // Check Auto (Backend handles fallback)
        const nsConfig = getLocalNsConfig() || {};
        const dateObj = new Date(date);

        // Always try fetching first
        try {
            await createBasalCheckin({
                nightscout_url: nsConfig.url,
                nightscout_token: nsConfig.token,
                created_at: dateObj.toISOString()
            });
            setMsg({ text: "✅ Guardado y analizado.", type: 'success' });
            if (onRefresh) onRefresh();
        } catch (e) {
            console.warn("Auto Checkin Failed:", e);
            // Fallback to manual
            setShowManualBg(true);
            const errMsg = e.message === "[object Object]" ? "Desc" : e.message;
            setMsg({ text: `⚠️ Fallo Auto: ${errMsg}. Usa manual.`, type: 'warning' });
        }
        setLoading(false);
        setLoading(false);
    };

    const handleManualCheckin = async () => {
        const bgVal = parseFloat(manualBg);
        if (isNaN(bgVal)) {
            setMsg({ text: "BG inválida", type: 'error' });
            return;
        }
        setLoading(true);
        try {
            await createBasalCheckin({
                manual_bg: bgVal,
                manual_trend: "Manual",
                created_at: new Date(date).toISOString()
            });
            setMsg({ text: "✅ Check-in manual guardado.", type: 'success' });
            setShowManualBg(false);
            setManualBg('');
            if (onRefresh) onRefresh();
        } catch (e) {
            setMsg({ text: "Error: " + e.message, type: 'error' });
        } finally {
            setLoading(false);
        }
    };

    const handleScanNight = async () => {
        setLoading(true);
        setMsg({ text: "Analizando noche (00h-06h)...", type: 'info' });
        try {
            const config = getLocalNsConfig() || {};
            await runNightScan(config); // defaults to today (scans last night)
            setMsg({ text: "✅ Análisis nocturno completado.", type: 'success' });
            if (onRefresh) onRefresh();
        } catch (e) {
            setMsg({ text: "Error: " + e.message, type: 'error' });
        } finally {
            setLoading(false);
        }
    };

    const calculateLateDose = () => {
        // Current Time
        const now = new Date();
        const currentH = now.getHours() + (now.getMinutes() / 60);

        // Usual Time
        const [uH, uM] = usualTime.split(':').map(Number);
        const usualH = uH + (uM / 60);

        // Diff
        let diff = currentH - usualH;
        if (diff < 0) diff += 24; // e.g. Usual 22:00, Now 02:00 -> -20 -> +4.

        // Logic check: Am I late today or early for tomorrow?
        // Assuming "Late" means positive delay < 18h.

        let reductionFactor = 1;
        let advice = "";
        let color = "var(--text)";

        if (diff <= 0.5) {
            setCalcResult({ u: Number(usualDose), msg: "Estás a tiempo (o muy poco retraso). Dosis completa." });
            return;
        }

        if (diff > 12) {
            setCalcResult({ u: 0, msg: `⚠️ Retraso de ${diff.toFixed(1)}h es excesivo (>12h). Riesgo de solapamiento mañana. Consultar médico o saltar dosis.`, isDanger: true });
            return;
        }

        // Linear reduction: Cover remaining hours until next scheduled dose (24 - diff).
        // Needed coverage = (24 - diff) hours.
        // Full dose covers 24h.
        // Adjusted = Usual * ( (24-diff)/24 )

        const adjusted = Number(usualDose) * ((24 - diff) / 24);
        const rounded = Math.round(adjusted * 2) / 2; // Round to 0.5

        setCalcResult({
            u: rounded,
            diff: diff.toFixed(1),
            msg: `Retraso de ${diff.toFixed(1)}h. Para no solapar con la dosis de mañana, cubre solo las ${Math.round(24 - diff)}h restantes.`
        });
    };

    const applyCalc = () => {
        if (calcResult && !calcResult.isDanger) {
            setDose(String(calcResult.u));
            setShowLateCalc(false);
            setCalcResult(null);
        }
    };

    return (
        <Card className="stack" style={{ marginBottom: '1rem' }}>
            <h3 style={{ margin: '0 0 1rem 0', fontSize: '1.1rem' }}>Registrar / Check-in</h3>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
                <div>
                    <label style={{ fontSize: '0.75rem', fontWeight: 700, color: '#64748b', display: 'block', marginBottom: '0.25rem' }}>DOSIS (U)</label>
                    <input
                        type="number" step="0.5" placeholder="0.0"
                        value={dose} onChange={e => setDose(e.target.value)}
                        style={{ width: '100%', padding: '0.6rem', fontSize: '1.1rem', border: '1px solid #cbd5e1', borderRadius: '8px' }}
                    />
                </div>
                <div>
                    <label style={{ fontSize: '0.75rem', fontWeight: 700, color: '#64748b', display: 'block', marginBottom: '0.25rem' }}>FECHA/HORA</label>
                    <input
                        type="datetime-local"
                        value={date} onChange={e => setDate(e.target.value)}
                        style={{ width: '100%', padding: '0.7rem', fontSize: '0.9rem', border: '1px solid #cbd5e1', borderRadius: '8px' }}
                    />
                </div>
            </div>


            {/* Late Calculator Popup */}
            {
                showLateCalc && (
                    <div className="fade-in" style={{
                        marginBottom: '1rem', background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: '8px', padding: '1rem'
                    }}>
                        <div style={{ fontWeight: 700, color: '#1e40af', marginBottom: '0.5rem', display: 'flex', justifyContent: 'space-between' }}>
                            <span>⏰ Calculadora de Olvido</span>
                            <button onClick={() => setShowLateCalc(false)} style={{ border: 'none', background: 'transparent', cursor: 'pointer' }}>✖</button>
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '10px' }}>
                            <div>
                                <label style={{ fontSize: '0.75rem', color: '#64748b' }}>H. Habitual</label>
                                <input type="time" value={usualTime} onChange={e => setUsualTime(e.target.value)} style={{ width: '100%', padding: '0.5rem', borderRadius: '6px', border: '1px solid #cbd5e1' }} />
                            </div>
                            <div>
                                <label style={{ fontSize: '0.75rem', color: '#64748b' }}>Dosis Normal</label>
                                <input type="number" value={usualDose} onChange={e => setUsualDose(e.target.value)} style={{ width: '100%', padding: '0.5rem', borderRadius: '6px', border: '1px solid #cbd5e1' }} />
                            </div>
                        </div>

                        <Button onClick={calculateLateDose} style={{ width: '100%', padding: '0.5rem', fontSize: '0.9rem', marginBottom: '10px' }}>Calcular Ajuste</Button>

                        {calcResult && (
                            <div style={{ background: '#fff', padding: '0.8rem', borderRadius: '6px', border: calcResult.isDanger ? '1px solid #fca5a5' : '1px solid #cbd5e1' }}>
                                <div style={{ fontSize: '0.9rem', color: calcResult.isDanger ? '#dc2626' : '#334155', marginBottom: '5px' }}>
                                    {calcResult.msg}
                                </div>
                                {!calcResult.isDanger && (
                                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '0.5rem' }}>
                                        <span style={{ fontSize: '1.5rem', fontWeight: 800, color: 'var(--primary)' }}>{calcResult.u} U</span>
                                        <Button size="sm" onClick={applyCalc}>Usar esta dosis</Button>
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                )
            }

            {
                !showLateCalc && (
                    <div style={{ textAlign: 'right', marginBottom: '0.5rem' }}>
                        <button onClick={() => setShowLateCalc(true)} style={{ fontSize: '0.75rem', color: 'var(--primary)', textDecoration: 'underline', background: 'none', border: 'none', cursor: 'pointer' }}>
                            ⏰ ¿Llegas tarde? Calcular ajuste
                        </button>
                    </div>
                )
            }

            <div style={{ margin: '1rem 0' }}>
                <InjectionSiteSelector
                    type="basal"
                    selected={injectionSite}
                    onSelect={setInjectionSite}
                />
            </div>

            {
                showManualBg && (
                    <div className="fade-in" style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', marginTop: '0.8rem', border: '1px solid #e2e8f0' }}>
                        <label style={{ fontSize: '0.85rem', fontWeight: 700, color: '#475569', display: 'block', marginBottom: '0.5rem' }}>GLUCOSA MANUAL (mg/dL)</label>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.8rem' }}>
                            <input
                                type="number" placeholder="Ej: 110"
                                value={manualBg} onChange={e => setManualBg(e.target.value)}
                                style={{ width: '100%', padding: '0.8rem', fontSize: '1.2rem', border: '1px solid #cbd5e1', borderRadius: '8px', textAlign: 'center' }}
                            />
                            <Button onClick={handleManualCheckin} disabled={loading} style={{ width: '100%', padding: '0.8rem' }}>Guardar</Button>
                        </div>
                    </div>
                )
            }

            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
                <Button variant="ghost" onClick={handleSaveSimple} disabled={loading} style={{ border: '1px solid #e2e8f0', flex: 1 }}>
                    {loading ? '...' : 'Solo Guardar'}
                </Button>
                <Button onClick={handleCheckinWake} disabled={loading} style={{ flex: 1.5 }}>
                    {loading ? '...' : '☀️ Al Levantarme'}
                </Button>
            </div>

            <Button variant="secondary" onClick={handleScanNight} disabled={loading} style={{ width: '100%' }}>
                🌙 Analizar Noche (00h-06h)
            </Button>

            {
                msg && (
                    <div style={{
                        marginTop: '0.5rem', padding: '0.5rem', borderRadius: '6px', fontSize: '0.85rem', textAlign: 'center',
                        background: msg.type === 'error' ? '#fee2e2' : (msg.type === 'warning' ? '#fef3c7' : '#dcfce7'),
                        color: msg.type === 'error' ? '#991b1b' : (msg.type === 'warning' ? '#92400e' : '#166534')
                    }}>
                        {msg.text}
                    </div>
                )
            }
        </Card >
    );
}

function BasalAdviceSection() {
    const [advice, setAdvice] = useState(null);
    const [loading, setLoading] = useState(true);

    const load = async () => {
        try {
            const res = await getBasalAdvice(3);
            setAdvice(res);
        } catch (e) {
            setAdvice({ error: e.message });
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { load(); }, []);

    if (loading) return <Card style={{ marginBottom: '1rem', textAlign: 'center', color: '#64748b' }}>Analizando...</Card>;
    if (!advice) return null;

    let color = "#64748b";
    let icon = "ℹ️";
    const msg = advice.message || (advice.error ? "Error" : "");

    if (msg.includes("OK")) {
        color = "var(--success)"; icon = "✅";
    } else if (msg.includes("hipoglucemias")) {
        color = "var(--danger)"; icon = "🚨";
    } else if (msg.includes("alza") || msg.includes("baja")) {
        color = "var(--warning)"; icon = "⚠️";
    }

    return (
        <Card style={{ marginBottom: '1rem', borderLeft: `4px solid ${color}` }}>
            <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '1rem' }}>Estado Basal</h3>
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-start' }}>
                <div style={{ fontSize: '1.2rem' }}>{icon}</div>
                <div>
                    <div style={{ fontWeight: 600, color: '#334155', marginBottom: '0.2rem' }}>
                        {advice.error || advice.message}
                    </div>
                    {!advice.error && (
                        <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                            Confianza: <span style={{ textTransform: 'uppercase', fontWeight: 700 }}>{advice.confidence === 'high' ? 'Alta' : (advice.confidence === 'medium' ? 'Media' : 'Baja')}</span>
                        </div>
                    )}
                </div>
            </div>
        </Card>
    );
}

function BasalImpactSection() {
    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(false);

    const evalImpact = async (days) => {
        setLoading(true);
        try {
            const res = await evaluateBasalChange(days);
            setResult(res);
        } catch (e) {
            alert(typeof e.message === 'string' ? e.message : JSON.stringify(e));
        } finally {
            setLoading(false);
        }
    };

    return (
        <Card style={{ marginBottom: '1rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <h3 style={{ margin: 0, fontSize: '1rem' }}>Impacto Cambios</h3>
                <span style={{ fontSize: '0.7rem', background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px', color: '#64748b' }}>Memoria de efecto</span>
            </div>

            {result && (
                <div style={{ marginBottom: '1rem', background: '#f8fafc', padding: '1rem', borderRadius: '8px', borderLeft: `4px solid ${result.result === 'improved' ? 'var(--success)' : (result.result === 'worse' ? 'var(--danger)' : '#f59e0b')}` }}>
                    <div style={{ fontWeight: 700, color: result.result === 'improved' ? 'var(--success)' : (result.result === 'worse' ? 'var(--danger)' : '#f59e0b') }}>
                        {result.result === 'improved' ? '✅ MEJORÍA' : (result.result === 'worse' ? '📉 EMPEORAMIENTO' : '❓ INSUFICIENTE')}
                    </div>
                    <div style={{ marginTop: '0.4rem', fontSize: '0.9rem', color: '#334155' }}>{result.summary}</div>
                </div>
            )}

            <div style={{ display: 'flex', gap: '0.5rem' }}>
                <Button variant="secondary" onClick={() => evalImpact(7)} disabled={loading} style={{ flex: 1, fontSize: '0.85rem' }}>📊 Evaluar (7 días)</Button>
                <Button variant="ghost" onClick={() => evalImpact(14)} disabled={loading} style={{ flex: 1, fontSize: '0.85rem' }}>14 días</Button>
            </div>
        </Card>
    );
}

function BasalTimelineSection() {
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(true);

    const load = async () => {
        try {
            const res = await getBasalTimeline(14);
            setItems(res.items || []);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { load(); }, []);

    const handleAnalyzItem = async (dateStr) => {
        if (!confirm(`¿Analizar noche del ${dateStr}?`)) return;
        try {
            const config = getLocalNsConfig() || {};
            // if (!config) throw new Error("Configurar Nightscout");
            const res = await runNightScan(config, dateStr);
            console.log(res);

            let msg = "✅ Análisis Completado.";
            if (res.had_hypo) msg += " Se detectó hipoglucemia.";
            else msg += " Noche estable (OK).";

            alert(msg);
            load(); // Reload
        } catch (e) {
            alert(typeof e.message === 'string' ? e.message : "Error desconocido al analizar");
        }
    };

    const handleAnalyzeAll = async () => {
        const pending = items.filter(i => i.night_had_hypo === null);
        if (pending.length === 0) return alert("No hay noches pendientes de analizar.");

        if (!confirm(`Se analizarán ${pending.length} noches pendientes. Esto puede tardar unos segundos. ¿Continuar?`)) return;

        setLoading(true);
        try {
            const config = getLocalNsConfig() || {};
            // if (!config) throw new Error("Configurar Nightscout");

            let processed = 0;
            // Process sequentially to be gentle on API
            for (const item of pending) {
                try {
                    await runNightScan(config, item.date);
                    processed++;
                } catch (err) {
                    console.error(`Error analizando ${item.date}:`, err);
                }
            }
            alert(`Proceso finalizado. ${processed}/${pending.length} noches analizadas.`);
            load();
        } catch (e) {
            alert(typeof e.message === 'string' ? e.message : "Error en proceso masivo");
            setLoading(false); // only if error caught here, otherwise load() clears it
        }
    };

    return (
        <section>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <h3 style={{ margin: 0, color: '#64748b', fontSize: '1rem' }}>Historial (14 días)</h3>
                {items.some(i => i.night_had_hypo === null) && (
                    <button
                        onClick={handleAnalyzeAll}
                        style={{ fontSize: '0.8rem', padding: '0.4rem 0.8rem', background: '#e0f2fe', color: '#0369a1', border: 'none', borderRadius: '6px', cursor: 'pointer', fontWeight: 600 }}
                    >
                        ⚡ Analizar Pendientes
                    </button>
                )}
            </div>
            <div className="card" style={{ padding: 0, overflow: 'hidden', border: '1px solid #e2e8f0', borderRadius: '12px' }}>
                <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', textAlign: 'left', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                        <thead style={{ background: '#f8fafc', color: '#64748b', fontSize: '0.75rem' }}>
                            <tr>
                                <th style={{ padding: '0.75rem' }}>Fecha</th>
                                <th style={{ padding: '0.75rem' }}>Basal</th>
                                <th style={{ padding: '0.75rem' }}>Despertar</th>
                                <th style={{ padding: '0.75rem' }}>Noche</th>
                            </tr>
                        </thead>
                        <tbody>
                            {loading && <tr><td colSpan="4" style={{ textAlign: 'center', padding: '1rem' }}>Cargando...</td></tr>}
                            {!loading && items.length === 0 && <tr><td colSpan="4" style={{ textAlign: 'center', padding: '1rem' }}>No hay datos</td></tr>}
                            {!loading && items.map((item, idx) => {
                                const d = new Date(item.date);
                                const dateStr = d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric' });

                                return (
                                    <tr key={idx} style={{ borderBottom: '1px solid #f1f5f9' }}>
                                        <td style={{ padding: '0.75rem', color: '#334155' }}>
                                            {dateStr}
                                            <button
                                                onClick={async (e) => {
                                                    e.stopPropagation();
                                                    if (confirm(`¿Borrar registro del ${dateStr}?`)) {
                                                        try {
                                                            const { deleteHistoryEntry } = await import('../lib/api');
                                                            await deleteHistoryEntry(item.date);
                                                            load();
                                                        } catch (err) { alert(err.message); }
                                                    }
                                                }}
                                                style={{ border: 'none', background: 'transparent', cursor: 'pointer', marginLeft: '8px', color: '#cbd5e1', fontSize: '0.9rem' }}
                                                title="Borrar entrada"
                                            >
                                                🗑️
                                            </button>
                                        </td>
                                        <td style={{ padding: '0.75rem', fontWeight: 700, color: '#3b82f6' }}>
                                            {item.dose_u ? item.dose_u + ' U' : '-'}
                                        </td>
                                        <td style={{ padding: '0.75rem', color: '#334155' }}>
                                            {item.wake_bg ? (
                                                <>
                                                    <strong>{Math.round(item.wake_bg)}</strong>
                                                    {item.wake_trend && <small style={{ color: '#94a3b8', marginLeft: '4px' }}>{item.wake_trend}</small>}
                                                </>
                                            ) : '--'}
                                        </td>
                                        <td style={{ padding: '0.75rem' }}>
                                            {item.night_had_hypo === true ? (
                                                <span style={{ color: 'var(--danger)', fontWeight: 700 }}>🌙 &lt; 70 {item.night_events_below_70 > 1 ? `(${item.night_events_below_70})` : ''}</span>
                                            ) : (item.night_had_hypo === false ? (
                                                <span style={{ color: 'var(--success)' }}>OK</span>
                                            ) : (
                                                <button
                                                    onClick={() => handleAnalyzItem(item.date)}
                                                    style={{ fontSize: '0.7rem', padding: '2px 6px', border: '1px solid #cbd5e1', background: 'transparent', borderRadius: '4px', cursor: 'pointer' }}
                                                >
                                                    🔍 Analizar
                                                </button>
                                            ))}
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            </div>
        </section>
    );
}

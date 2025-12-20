import React, { useState, useEffect } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { Card, Button, Input } from '../components/ui/Atoms';
import {
    getCalcParams, saveCalcParams,
    getSplitSettings, saveSplitSettings,
    getSettingsVersion
} from '../modules/core/store';
import {
    getNightscoutSecretStatus, saveNightscoutSecret, testNightscout,
    fetchHealth, exportUserData
} from '../lib/api';
import { IsfAnalyzer } from '../components/settings/IsfAnalyzer';

export default function SettingsPage() {
    const [activeTab, setActiveTab] = useState('ns'); // 'ns' | 'calc' | 'data' | 'analysis'

    return (
        <>
            <Header title="Ajustes" showBack={true} />
            <main className="page" style={{ paddingBottom: '80px' }}>
                <Card>
                    <div className="tabs" style={{ display: 'flex', borderBottom: '1px solid #e2e8f0', marginBottom: '1rem' }}>
                        <TabButton label="Nightscout" active={activeTab === 'ns'} onClick={() => setActiveTab('ns')} />
                        <TabButton label="Cálculo" active={activeTab === 'calc'} onClick={() => setActiveTab('calc')} />
                        <TabButton label="Análisis" active={activeTab === 'analysis'} onClick={() => setActiveTab('analysis')} />
                        <TabButton label="Datos" active={activeTab === 'data'} onClick={() => setActiveTab('data')} />
                    </div>

                    <div style={{ display: activeTab === 'ns' ? 'block' : 'none' }}>
                        <NightscoutPanel />
                    </div>
                    <div style={{ display: activeTab === 'calc' ? 'block' : 'none' }}>
                        <CalcParamsPanel />
                    </div>
                    <div style={{ display: activeTab === 'analysis' ? 'block' : 'none' }}>
                        <IsfAnalyzer />
                    </div>
                    <div style={{ display: activeTab === 'data' ? 'block' : 'none' }}>
                        <DataPanel />
                    </div>
                </Card>

                {activeTab === 'data' && (
                    <Card title="Estado del Backend" className="mt-4">
                        <HealthCheck />
                    </Card>
                )}
            </main>
            <BottomNav activeTab="settings" />
        </>
    );
}

function TabButton({ label, active, onClick }) {
    return (
        <button
            onClick={onClick}
            style={{
                flex: 1,
                padding: '0.75rem',
                background: 'none',
                border: 'none',
                borderBottom: active ? '2px solid var(--primary)' : '2px solid transparent',
                fontWeight: active ? 700 : 400,
                color: active ? 'var(--primary)' : 'var(--text-muted)',
                cursor: 'pointer'
            }}
        >
            {label}
        </button>
    );
}

// --- PANELS ---

function NightscoutPanel() {
    const [url, setUrl] = useState('');
    const [secret, setSecret] = useState('');
    const [hasSecret, setHasSecret] = useState(false);
    const [status, setStatus] = useState({ msg: '', type: 'neutral' }); // neutral, success, error
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        getNightscoutSecretStatus().then(res => {
            if (res.url) setUrl(res.url);
            setHasSecret(res.has_secret);
        }).catch(err => console.warn(err));
    }, []);

    const handleTest = async () => {
        setStatus({ msg: 'Probando...', type: 'neutral' });
        try {
            // Test existing if secret is empty but configured, or test new input
            let res;
            if (!secret && hasSecret) {
                const { getNightscoutStatus } = await import('../lib/api');
                res = await getNightscoutStatus();
                res = { ok: res.ok, message: res.error || "Conectado (Server)" };
            } else {
                res = await testNightscout({ url, token: secret });
            }

            setStatus({
                msg: res.ok ? "✅ Conectado Correctamente" : `❌ Error: ${res.message}`,
                type: res.ok ? 'success' : 'error'
            });
        } catch (e) {
            setStatus({ msg: `❌ Error: ${e.message}`, type: 'error' });
        }
    };

    const handleSave = async () => {
        if (!url) return alert("URL requerida");

        // Confirmation logic if secret is empty but previously set
        if (!secret && hasSecret) {
            if (!window.confirm("No has escrito el Token. ¿Guardar SIN cambiar el secreto? \n(Si has cambiado la URL, debes reescribir el secreto).")) {
                return;
            }
            // If they proceed, we assume they want to keep the secret. 
            // BUT backend upsert currently overwrites. Ideally we should have a flag "keep_secret".
            // For now we act as the legacy JS: Warn user to re-type.
            alert("Por seguridad, re-introduce el API Secret.");
            return;
        }

        setLoading(true);
        setStatus({ msg: 'Guardando...', type: 'neutral' });

        try {
            await saveNightscoutSecret({ url, api_secret: secret, enabled: true });
            setStatus({ msg: '✅ Guardado seguro.', type: 'success' });
            setSecret('');
            setHasSecret(true); // Now we definitely have it
        } catch (e) {
            setStatus({ msg: `❌ Error guardando: ${e.message}`, type: 'error' });
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="stack">
            <h3 style={{ marginTop: 0 }}>Conexión Nightscout</h3>
            <p className="text-muted text-sm">Tus credenciales se guardan encriptadas en la base de datos.</p>

            <Input label="URL Nightscout" value={url} onChange={e => setUrl(e.target.value)} placeholder="https://mi-nightscout.herokuapp.com" />

            <Input
                label="API Secret / Token"
                type="password"
                value={secret}
                onChange={e => setSecret(e.target.value)}
                placeholder={hasSecret ? "Configurado (Oculto) - Escribe para cambiar" : "API Secret"}
            />

            <div style={{ display: 'flex', gap: '0.5rem' }}>
                <Button variant="secondary" onClick={handleTest}>Probar</Button>
                <Button onClick={handleSave} disabled={loading}>{loading ? 'Guardando...' : 'Guardar'}</Button>
            </div>

            {status.msg && (
                <div style={{
                    padding: '0.8rem',
                    borderRadius: '8px',
                    marginTop: '1rem',
                    background: status.type === 'error' ? '#fee2e2' : (status.type === 'success' ? '#dcfce7' : '#f1f5f9'),
                    color: status.type === 'error' ? '#ef4444' : (status.type === 'success' ? '#166534' : '#334155'),
                    fontWeight: 600
                }}>
                    {status.msg}
                </div>
            )}
        </div>
    );
}

function CalcParamsPanel() {
    // Defaults
    const defaults = {
        breakfast: { icr: 10, isf: 50, target: 110 },
        lunch: { icr: 10, isf: 50, target: 110 },
        dinner: { icr: 10, isf: 50, target: 110 },
        snack: { icr: 10, isf: 50, target: 110 },
        dia_hours: 4,
        round_step_u: 0.5,
        max_bolus_u: 10,
        techne: { enabled: false, max_step_change: 0.5, safety_iob_threshold: 1.5 }
    };

    const [params, setParams] = useState(defaults);
    const [splitParams, setSplitParams] = useState(getSplitSettings());
    const [slot, setSlot] = useState('breakfast');
    const [status, setStatus] = useState(null);

    useEffect(() => {
        const p = getCalcParams();
        if (p) {
            // Deep merge for techne to ensure it exists
            const merged = {
                ...defaults,
                ...p,
                techne: { ...defaults.techne, ...(p.techne || {}) }
            };
            setParams(merged);
        }
        else saveCalcParams(defaults); // Init if empty
    }, []);

    const handleChange = (field, value, isSlot = false) => {
        if (isSlot) {
            setParams(prev => ({
                ...prev,
                [slot]: { ...prev[slot], [field]: parseFloat(value) }
            }));
        } else {
            setParams(prev => ({
                ...prev,
                [field]: parseFloat(value)
            }));
        }
    };

    const handleSave = () => {
        saveCalcParams(params);
        setStatus('Parámetros guardados correctamente.');
        setTimeout(() => setStatus(null), 3000);
    };

    const handleSaveSplit = () => {
        saveSplitSettings(splitParams);
        alert("Configuración de bolo dividido guardada.");
    };

    const slotData = params[slot] || defaults[slot];

    return (
        <div className="stack">
            <h3 style={{ marginTop: 0 }}>Parámetros Clínicos</h3>
            <p className="text-muted text-sm warning-text">Ajusta con ayuda médica profesional.</p>

            <div className="sub-tabs" style={{ display: 'flex', gap: '0.2rem', background: '#f1f5f9', padding: '0.2rem', borderRadius: '8px', marginBottom: '1rem' }}>
                {['breakfast', 'lunch', 'dinner', 'snack'].map(s => (
                    <button
                        key={s}
                        onClick={() => setSlot(s)}
                        style={{
                            flex: 1,
                            padding: '0.4rem',
                            border: 'none',
                            background: slot === s ? 'white' : 'transparent',
                            boxShadow: slot === s ? '0 1px 2px rgba(0,0,0,0.1)' : 'none',
                            borderRadius: '6px',
                            fontWeight: slot === s ? 600 : 400,
                            cursor: 'pointer',
                            textTransform: 'capitalize'
                        }}
                    >
                        {s === 'breakfast' ? 'Desay.' : (s === 'lunch' ? 'Comida' : (s === 'dinner' ? 'Cena' : 'Snack'))}
                    </button>
                ))}
            </div>

            <div className="stack">
                <Input label="Ratio (ICR - g/U)" type="number" value={slotData.icr} onChange={e => handleChange('icr', e.target.value, true)} />
                <Input label="Sensibilidad (ISF - mg/dL/U)" type="number" value={slotData.isf} onChange={e => handleChange('isf', e.target.value, true)} />
                <Input label="Objetivo (Target - mg/dL)" type="number" value={slotData.target} onChange={e => handleChange('target', e.target.value, true)} />
            </div>

            <hr style={{ margin: '1rem 0', borderColor: '#f1f5f9' }} />

            <div className="stack">
                <Input label="Duración Insulina (DIA - Horas)" type="number" value={params.dia_hours} onChange={e => handleChange('dia_hours', e.target.value)} />
                <Input label="Máximo Bolo (Seguridad - U)" type="number" value={params.max_bolus_u} onChange={e => handleChange('max_bolus_u', e.target.value)} />

                <label style={{ fontWeight: 600, fontSize: '0.9rem', color: '#475569' }}>Paso de redondeo</label>
                <select
                    style={{ width: '100%', padding: '0.6rem', borderRadius: '8px', border: '1px solid #cbd5e1' }}
                    value={params.round_step_u}
                    onChange={e => handleChange('round_step_u', e.target.value)}
                >
                    <option value="0.5">0.5 U</option>
                    <option value="1.0">1.0 U</option>
                    <option value="0.1">0.1 U</option>
                    <option value="0.05">0.05 U</option>
                </select>

                <div style={{ marginTop: '1rem', padding: '1rem', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.8rem', fontWeight: 600, marginBottom: params.techne?.enabled ? '1rem' : 0, cursor: 'pointer' }}>
                        <input
                            type="checkbox"
                            checked={params.techne?.enabled}
                            onChange={e => setParams(prev => ({ ...prev, techne: { ...prev.techne, enabled: e.target.checked } }))}
                            style={{ width: '1.2rem', height: '1.2rem' }}
                        />
                        Redondeo Inteligente (Techne)
                    </label>

                    {params.techne?.enabled && (
                        <div className="stack" style={{ gap: '0.8rem', marginTop: '0.5rem' }}>
                            <p className="text-sm text-muted" style={{ margin: 0 }}>
                                Usa la flecha de tendencia para decidir si redondear hacia arriba (↗) o abajo (↘).
                            </p>
                            <Input
                                label="Límite cambio máx (Seguridad - U)"
                                type="number"
                                value={params.techne.max_step_change}
                                onChange={e => setParams(prev => ({ ...prev, techne: { ...prev.techne, max_step_change: parseFloat(e.target.value) } }))}
                            />
                            <Input
                                label="Desactivar si IOB mayor que (U)"
                                type="number"
                                value={params.techne.safety_iob_threshold}
                                onChange={e => setParams(prev => ({ ...prev, techne: { ...prev.techne, safety_iob_threshold: parseFloat(e.target.value) } }))}
                            />
                        </div>
                    )}
                </div>
            </div>

            <Button onClick={handleSave} style={{ marginTop: '1rem' }}>Guardar Parámetros</Button>
            {status && <div className="text-teal text-center text-sm" style={{ marginTop: '0.5rem' }}>{status}</div>}

            <details style={{ marginTop: '2rem', border: '1px solid #e2e8f0', borderRadius: '8px', padding: '0.5rem' }}>
                <summary style={{ fontWeight: 600, cursor: 'pointer', padding: '0.5rem' }}>Avanzado: Bolo Dividido</summary>
                <div className="stack" style={{ padding: '1rem' }}>
                    <label style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                        <input type="checkbox" checked={splitParams.enabled_default} onChange={e => setSplitParams({ ...splitParams, enabled_default: e.target.checked })} />
                        Activar por defecto
                    </label>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
                        <Input label="% Ahora" type="number" value={splitParams.percent_now} onChange={e => setSplitParams({ ...splitParams, percent_now: parseInt(e.target.value) })} />
                        <Input label="Duración (min)" type="number" value={splitParams.duration_min} onChange={e => setSplitParams({ ...splitParams, duration_min: parseInt(e.target.value) })} />
                    </div>
                    <Input label="Recordar 2ª parte tras (min)" type="number" value={splitParams.later_after_min} onChange={e => setSplitParams({ ...splitParams, later_after_min: parseInt(e.target.value) })} />
                    <Button variant="secondary" onClick={handleSaveSplit}>Guardar Avanzado</Button>
                </div>
            </details>
        </div>
    );
}

function DataPanel() {
    const handleExport = async () => {
        try {
            const data = await exportUserData();
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `bolus_ai_export_${new Date().toISOString().slice(0, 10)}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        } catch (e) { alert(e.message); }
    };

    return (
        <div className="stack">
            <div style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px' }}>
                <h3 style={{ fontSize: '1.1rem', margin: '0 0 0.5rem 0' }}>Exportar Historial</h3>
                <p style={{ marginBottom: '1rem', color: '#64748b', fontSize: '0.9rem' }}>Descarga copia de seguridad de todos tus datos.</p>
                <Button variant="secondary" onClick={handleExport}>📥 Descargar Todo (JSON)</Button>
            </div>
            <div style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px' }}>
                <h3 style={{ fontSize: '1.1rem', margin: '0 0 0.5rem 0' }}>Notificaciones Push</h3>
                <p style={{ marginBottom: '1rem', color: '#64748b', fontSize: '0.9rem' }}>Recibe alertas de análisis.</p>
                <Button variant="ghost" onClick={() => alert("Próximamente")}>🔔 Activar</Button>
            </div>
        </div>
    );
}

function HealthCheck() {
    const [status, setStatus] = useState("Sin comprobar");

    const check = async () => {
        setStatus("Consultando...");
        try {
            const h = await fetchHealth();
            setStatus(JSON.stringify(h, null, 2));
        } catch (e) {
            setStatus("Error: " + e.message);
        }
    };

    return (
        <div>
            <Button variant="ghost" onClick={check} style={{ marginBottom: '0.5rem' }}>Comprobar Conexión</Button>
            <pre style={{ background: '#0f172a', color: '#22d3ee', padding: '0.5rem', borderRadius: '6px', overflowX: 'auto', fontSize: '0.75rem' }}>
                {status}
            </pre>
        </div>
    );
}

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
    fetchHealth, exportUserData, importUserData
} from '../lib/api';
import { IsfAnalyzer } from '../components/settings/IsfAnalyzer';

export default function SettingsPage() {
    const [activeTab, setActiveTab] = useState('ns'); // 'ns' | 'calc' | 'data' | 'analysis'

    return (
        <>
            <Header title="Ajustes" showBack={true} />
            <main className="page" style={{ paddingBottom: '80px' }}>
                <Card>
                    <div className="tabs" style={{ display: 'flex', borderBottom: '1px solid #e2e8f0', marginBottom: '1rem', overflowX: 'auto' }}>
                        <TabButton label="Nightscout" active={activeTab === 'ns'} onClick={() => setActiveTab('ns')} />
                        <TabButton label="Cálculo" active={activeTab === 'calc'} onClick={() => setActiveTab('calc')} />
                        <TabButton label="IA / Visión" active={activeTab === 'vision'} onClick={() => setActiveTab('vision')} />
                        <TabButton label="Análisis" active={activeTab === 'analysis'} onClick={() => setActiveTab('analysis')} />
                        <TabButton label="Datos" active={activeTab === 'data'} onClick={() => setActiveTab('data')} />
                        <TabButton label="Labs" active={activeTab === 'labs'} onClick={() => setActiveTab('labs')} />
                        <TabButton label="Bot" active={activeTab === 'bot'} onClick={() => setActiveTab('bot')} />
                    </div>

                    {activeTab === 'ns' && <NightscoutPanel />}
                    {activeTab === 'calc' && <CalcParamsPanel />}
                    {activeTab === 'vision' && <VisionPanel />}
                    {activeTab === 'bot' && <BotPanel />}
                    {activeTab === 'analysis' && <IsfAnalyzer />}
                    {activeTab === 'data' && <DataPanel />}
                    {activeTab === 'labs' && <LabsPanel />}
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
        absorption: { breakfast: 180, lunch: 180, dinner: 240, snack: 120 },
        schedule: { breakfast_start_hour: 5, lunch_start_hour: 13, dinner_start_hour: 20 },
        dia_hours: 4,
        round_step_u: 0.5,
        max_bolus_u: 10,
        round_step_u: 0.5,
        max_bolus_u: 10,
        techne: { enabled: false, max_step_change: 0.5, safety_iob_threshold: 1.5 },
        warsaw: { enabled: true, trigger_threshold_kcal: 300, safety_factor: 0.1, safety_factor_dual: 0.2 },
        autosens: { enabled: true, min_ratio: 0.7, max_ratio: 1.2 }
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
                techne: { ...defaults.techne, ...(p.techne || {}) },
                warsaw: { ...defaults.warsaw, ...(p.warsaw || {}) },
                autosens: { ...defaults.autosens, ...(p.autosens || {}) }
            };
            setParams(merged);
        }
        else saveCalcParams(defaults); // Init if empty
    }, []);

    const handleChange = (field, value, isSlot = false) => {
        if (isSlot) {
            setParams(prev => ({
                ...prev,
                [slot]: { ...prev[slot], [field]: value }
            }));
        } else {
            setParams(prev => ({
                ...prev,
                [field]: value
            }));
        }
    };

    const handleAbsorptionChange = (val) => {
        setParams(prev => ({
            ...prev,
            absorption: {
                ...prev.absorption,
                [slot]: parseInt(val)
            }
        }));
    };

    const handleSave = () => {
        // Deep clean and parse numbers
        const clean = JSON.parse(JSON.stringify(params));
        const p = (v) => {
            if (typeof v === 'string') {
                return parseFloat(v.replace(',', '.')) || 0;
            }
            return v;
        };

        ['breakfast', 'lunch', 'dinner', 'snack'].forEach(s => {
            if (clean[s]) {
                clean[s].icr = p(clean[s].icr);
                clean[s].isf = p(clean[s].isf);
                clean[s].target = p(clean[s].target);
            }
        });
        clean.dia_hours = p(clean.dia_hours);
        if (clean.schedule) {
            clean.schedule.breakfast_start_hour = parseInt(clean.schedule.breakfast_start_hour);
            clean.schedule.lunch_start_hour = parseInt(clean.schedule.lunch_start_hour);
            clean.schedule.dinner_start_hour = parseInt(clean.schedule.dinner_start_hour);
        }
        clean.max_bolus_u = p(clean.max_bolus_u);

        saveCalcParams(clean);
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
            <SchedulePanel settings={params} onChange={setParams} />
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
                <Input label="Ratio (ICR - g/U)" type="text" inputMode="decimal" value={slotData.icr} onChange={e => handleChange('icr', e.target.value, true)} />
                <Input label="Sensibilidad (ISF - mg/dL/U)" type="text" inputMode="decimal" value={slotData.isf} onChange={e => handleChange('isf', e.target.value, true)} />
                <Input label="Objetivo (Target - mg/dL)" type="number" value={slotData.target} onChange={e => handleChange('target', e.target.value, true)} />
                <Input label="Absorción (min)" type="number" value={params.absorption?.[slot] ?? 180} onChange={e => handleAbsorptionChange(e.target.value)} />
            </div>

            <hr style={{ margin: '1rem 0', borderColor: '#f1f5f9' }} />

            <div className="stack">
                <div className="form-group">
                    <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 600 }}>Tipo de Insulina (Perfil)</label>
                    <select
                        value={params.insulin_model || 'linear'}
                        onChange={e => {
                            const model = e.target.value;
                            let name = "Rápida";
                            let wait = 15;

                            if (model === 'fiasp') { name = 'Fiasp'; wait = 5; }
                            else if (model === 'novorapid') { name = 'NovoRapid'; wait = 15; }

                            setParams(prev => ({
                                ...prev,
                                insulin_model: model,
                                insulin: {
                                    ...prev.insulin,
                                    name: name,
                                    pre_bolus_min: wait
                                }
                            }));
                        }}
                        style={{
                            width: '100%', padding: '0.8rem', borderRadius: '8px',
                            border: '1px solid #cbd5e1', background: 'white',
                            fontSize: '1rem'
                        }}
                    >
                        <option value="linear">Estándar (Rápida Genérica)</option>
                        <option value="fiasp">Fiasp / Ultra-Rápida</option>
                        <option value="novorapid">NovoRapid / Rápida</option>
                    </select>
                    <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '4px' }}>
                        {params.insulin_model === 'fiasp' ? '💡 Configurado: Pico 55m, DIA 4-5h' :
                            params.insulin_model === 'novorapid' ? '💡 Configurado: Pico 75m, DIA 4-5h' : 'Modelo genérico'}
                    </div>
                </div>

                <Input label="Duración Insulina (DIA - Horas)" type="number" value={params.dia_hours} onChange={e => handleChange('dia_hours', e.target.value)} />

                {/* TDD Assistant */}
                <div style={{ background: '#f0f9ff', padding: '1rem', borderRadius: '8px', border: '1px solid #bae6fd', margin: '1rem 0' }}>
                    <h4 style={{ margin: '0 0 0.5rem 0', color: '#0369a1', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        🧮 Asistente TDD
                    </h4>
                    <p className="text-sm text-muted" style={{ marginBottom: '1rem' }}>
                        Si conoces tu Total Diario de Insulina (Basal + Bolos), podemos sugerir tus ratios base.
                    </p>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                        <div>
                            <label style={{ fontSize: '0.9rem', fontWeight: 600, color: '#0369a1', marginBottom: '0.5rem', display: 'block' }}>
                                Total Diario de Insulina (TDD)
                            </label>
                            <input
                                type="number"
                                inputMode="decimal"
                                placeholder="Ej: 23"
                                style={{
                                    width: '100%',
                                    padding: '1rem',
                                    borderRadius: '12px',
                                    border: '2px solid #e2e8f0', // Standard app border
                                    fontSize: '1.5rem',
                                    outline: 'none',
                                    color: '#1e293b', // Standard text dark
                                    fontWeight: 'bold',
                                    background: 'white',
                                    appearance: 'textfield',
                                    textAlign: 'center' // Center for better symmetry in big inputs
                                }}
                                onFocus={(e) => e.target.style.borderColor = '#3b82f6'} // Blue on focus only
                                onBlur={(e) => e.target.style.borderColor = '#e2e8f0'}
                                onChange={(e) => {
                                    const val = parseFloat(e.target.value);
                                    e.target.setAttribute('data-tdd', val || 0);
                                }}
                            />
                        </div>

                        <Button variant="secondary" onClick={(e) => {
                            // Find input by traversing up
                            const container = e.currentTarget.parentElement;
                            const input = container.querySelector('input');
                            const tdd = parseFloat(input.getAttribute('data-tdd'));

                            if (!tdd || tdd <= 0) return alert("Introduce un TDD válido (ej. 23).");

                            // Formula: ISF = 1800 / TDD
                            const sugIsf = Math.round(1800 / tdd);

                            // Calculate ICR just for info msg
                            const sugIcr = Math.round((500 / tdd) * 10) / 10;

                            const msg = `Sugerencia para TDD ${tdd}U:\n\n` +
                                `• Sensibilidad (ISF): ${sugIsf} (Recomendado)\n` +
                                `• Ratio Comida (ICR): ~${sugIcr} (Referencia)\n\n` +
                                `¿Aplicar SOLO el ISF de ${sugIsf}?`;

                            if (window.confirm(msg)) {
                                setParams(prev => ({
                                    ...prev,
                                    breakfast: { ...prev.breakfast, isf: sugIsf },
                                    lunch: { ...prev.lunch, isf: sugIsf },
                                    dinner: { ...prev.dinner, isf: sugIsf },
                                    snack: { ...prev.snack, isf: sugIsf }
                                }));
                                alert(`✅ Sensibilidad actualizada a ${sugIsf} en todos los horarios.`);
                            }
                        }} style={{ padding: '0.8rem', fontSize: '1rem', justifyContent: 'center' }}>
                            ✨ Calcular y Aplicar ISF
                        </Button>
                    </div>
                    <div id="tdd-feedback" style={{ marginTop: '0.5rem', fontSize: '0.8rem', color: '#64748b' }}>
                        Nota: Esta herramienta solo ajusta tu Factor de Sensibilidad (Corrección).
                    </div>
                </div>

                <Input label="Máximo Bolo (Seguridad - U)" type="number" value={params.max_bolus_u} onChange={e => handleChange('max_bolus_u', e.target.value)} />

                <h4 style={{ margin: '0.5rem 0', color: '#475569', fontSize: '1rem' }}>Configuración de Insulina</h4>
                <div style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0', marginBottom: '1rem' }}>

                    <Input
                        label="Espera Pre-comida (Min)"
                        type="number"
                        value={params.insulin?.pre_bolus_min ?? 15}
                        onChange={e => setParams(prev => ({ ...prev, insulin: { ...prev.insulin, pre_bolus_min: parseFloat(e.target.value) } }))}
                        placeholder="Ej: 15 (Rápida), 5 (Ultra)"
                    />
                    <p className="text-sm text-muted" style={{ marginTop: '-0.5rem' }}>
                        Tiempo recomendado entre inyección e ingesta.
                    </p>
                </div>

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

            <div style={{ marginTop: '1rem', padding: '1rem', background: '#fff7ed', borderRadius: '8px', border: '1px solid #fed7aa' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.8rem', fontWeight: 600, color: '#9a3412', marginBottom: params.warsaw?.enabled ? '1rem' : 0, cursor: 'pointer' }}>
                    <input
                        type="checkbox"
                        checked={params.warsaw?.enabled}
                        onChange={e => setParams(prev => ({ ...prev, warsaw: { ...prev.warsaw, enabled: e.target.checked } }))}
                        style={{ width: '1.2rem', height: '1.2rem' }}
                    />
                    Método Warsaw (Grasas y Proteínas)
                </label>

                {params.warsaw?.enabled && (
                    <div className="stack" style={{ gap: '0.8rem', marginTop: '0.5rem' }}>
                        <p className="text-sm text-muted" style={{ margin: 0 }}>
                            Si la comida tiene muchas grasas/proteínas, se sugerirá un <strong>Bolo Extendido</strong> para evitar subidas tardías.
                        </p>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                            <Input
                                label="Activar si Kcal Grasa/Prot >"
                                type="number"
                                value={params.warsaw.trigger_threshold_kcal}
                                onChange={e => setParams(prev => ({ ...prev, warsaw: { ...prev.warsaw, trigger_threshold_kcal: parseInt(e.target.value) } }))}
                                placeholder="Ej: 300"
                            />
                            <Input
                                label="Factor Bolo Simple (0.1 = 10%)"
                                type="number"
                                step="0.1"
                                value={params.warsaw.safety_factor}
                                onChange={e => setParams(prev => ({ ...prev, warsaw: { ...prev.warsaw, safety_factor: parseFloat(e.target.value) } }))}
                                placeholder="0.1"
                            />
                            <Input
                                label="Factor Bolo Dual (0.2 = 20%)"
                                type="number"
                                step="0.1"
                                value={params.warsaw.safety_factor_dual ?? 0.2}
                                onChange={e => setParams(prev => ({ ...prev, warsaw: { ...prev.warsaw, safety_factor_dual: parseFloat(e.target.value) } }))}
                                placeholder="0.2"
                            />
                        </div>
                        <div style={{ fontSize: '0.75rem', color: '#c2410c' }}>
                            💡 <strong>Ejemplo:</strong> Con {params.warsaw.trigger_threshold_kcal} kcal (aprox {(params.warsaw.trigger_threshold_kcal / 9).toFixed(0)}g de grasa), se activará el aviso.
                            <br />
                            🛡️ <strong>Seguridad:</strong> Se cubre solo el {Math.round(params.warsaw.safety_factor * 100)}% de esas grasas (10% es recomendado para empezar).
                        </div>
                    </div>
                )}
            </div>

            <div style={{ marginTop: '1rem', padding: '1rem', background: '#f0fdf4', borderRadius: '8px', border: '1px solid #bbf7d0' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.8rem', fontWeight: 600, color: '#166534', marginBottom: params.autosens?.enabled ? '1rem' : 0, cursor: 'pointer' }}>
                    <input
                        type="checkbox"
                        checked={params.autosens?.enabled}
                        onChange={e => setParams(prev => ({ ...prev, autosens: { ...prev.autosens, enabled: e.target.checked } }))}
                        style={{ width: '1.2rem', height: '1.2rem' }}
                    />
                    Autosens (Sensibilidad Dinámica) 🤖
                </label>

                {params.autosens?.enabled && (
                    <div className="stack" style={{ gap: '0.8rem', marginTop: '0.5rem' }}>
                        <p className="text-sm text-muted" style={{ margin: 0 }}>
                            Ajusta tus Ratios e ISF automáticamente según tu resistencia o sensibilidad de las últimas 24h.
                        </p>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                            <Input
                                label="Ratio Mínimo (Sensibilidad)"
                                type="number"
                                step="0.05"
                                value={params.autosens.min_ratio}
                                onChange={e => setParams(prev => ({ ...prev, autosens: { ...prev.autosens, min_ratio: parseFloat(e.target.value) } }))}
                            />
                            <Input
                                label="Ratio Máximo (Resistencia)"
                                type="number"
                                step="0.05"
                                value={params.autosens.max_ratio}
                                onChange={e => setParams(prev => ({ ...prev, autosens: { ...prev.autosens, max_ratio: parseFloat(e.target.value) } }))}
                            />
                        </div>
                        <div style={{ fontSize: '0.75rem', color: '#15803d' }}>
                            💡 <strong>Limites:</strong> Si Autosens detecta una desviación, nunca aplicará un factor fuera de este rango ({params.autosens.min_ratio}x - {params.autosens.max_ratio}x) por seguridad.
                        </div>
                    </div>
                )}
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
        </div >
    );
}

function DataPanel() {
    const fileInputRef = React.useRef(null);
    const [importing, setImporting] = useState(false);

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

    const handleImportClick = () => {
        fileInputRef.current.click();
    };

    const handleFileChange = async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        if (!window.confirm("⚠️ IMPORTANTE: Al importar, se sobreescribirán los datos existentes si coinciden los IDs. \n\n¿Seguro que quieres restaurar esta copia de seguridad?")) {
            e.target.value = null;
            return;
        }

        setImporting(true);
        const reader = new FileReader();
        reader.onload = async (evt) => {
            try {
                const json = JSON.parse(evt.target.result);
                const stats = await importUserData(json);
                alert(`✅ Importación completada.\n\nResumen:\n${JSON.stringify(stats, null, 2)}`);
                window.location.reload();
            } catch (err) {
                alert("❌ Error al importar: " + err.message);
            } finally {
                setImporting(false);
                if (fileInputRef.current) fileInputRef.current.value = null;
            }
        };
        reader.readAsText(file);
    };

    return (
        <div className="stack">
            <div style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px' }}>
                <h3 style={{ fontSize: '1.1rem', margin: '0 0 0.5rem 0' }}>Exportar Historial</h3>
                <p style={{ marginBottom: '1rem', color: '#64748b', fontSize: '0.9rem' }}>Descarga copia de seguridad de todos tus datos.</p>
                <Button variant="secondary" onClick={handleExport}>📥 Descargar Todo (JSON)</Button>
            </div>

            <div style={{ background: '#f0fdf4', padding: '1rem', borderRadius: '8px', border: '1px solid #bbf7d0' }}>
                <h3 style={{ fontSize: '1.1rem', margin: '0 0 0.5rem 0' }}>Restaurar / Importar</h3>
                <p style={{ marginBottom: '1rem', color: '#64748b', fontSize: '0.9rem' }}>Carga un archivo JSON previamente exportado para restaurar tu configuración y datos.</p>
                <input
                    type="file"
                    accept=".json"
                    style={{ display: 'none' }}
                    ref={fileInputRef}
                    onChange={handleFileChange}
                />
                <Button variant="secondary" onClick={handleImportClick} disabled={importing} style={{ borderColor: '#16a34a', color: '#16a34a' }}>
                    {importing ? 'Importando...' : '📤 Seleccionar Archivo...'}
                </Button>
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

function VisionPanel() {
    const [config, setConfig] = useState({
        provider: 'gemini',
        gemini_key: '',
        gemini_model: 'gemini-2.0-flash-exp',
        openai_key: '',
        openai_model: 'gpt-4o'
    });
    const [loading, setLoading] = useState(true);
    const [status, setStatus] = useState(null);

    useEffect(() => {
        const params = getCalcParams() || {};
        if (params.vision) {
            setConfig(prev => ({ ...prev, ...params.vision }));
        }
        setLoading(false);
    }, []);

    const handleChange = (field, value) => {
        setConfig(prev => ({ ...prev, [field]: value }));
    };

    const handleSave = () => {
        const current = getCalcParams() || {};
        const newParams = {
            ...current,
            vision: config
        };
        saveCalcParams(newParams);
        setStatus('✅ Configuración de Visión guardada.');
        setTimeout(() => setStatus(null), 3000);
    };

    if (loading) return <div className="p-4 text-center">Cargando...</div>;

    return (
        <div className="stack">
            <h3 style={{ marginTop: 0 }}>Inteligencia Artificial (Visión)</h3>
            <p className="text-muted text-sm">
                Configura el proveedor de IA para el reconocimiento de alimentos.
            </p>

            <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 600 }}>Proveedor Activo</label>
            <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.5rem' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', padding: '0.5rem', background: config.provider === 'gemini' ? '#eff6ff' : 'transparent', borderRadius: '6px', border: config.provider === 'gemini' ? '1px solid #3b82f6' : '1px solid #e2e8f0' }}>
                    <input
                        type="radio"
                        name="vision_provider"
                        value="gemini"
                        checked={config.provider === 'gemini'}
                        onChange={() => handleChange('provider', 'gemini')}
                    />
                    <div style={{ display: 'flex', flexDirection: 'column' }}>
                        <span style={{ fontWeight: 600 }}>Google Gemini</span>
                        <span style={{ fontSize: '0.75rem', color: '#64748b' }}>Recomendado (Rápido)</span>
                    </div>
                </label>

                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', padding: '0.5rem', background: config.provider === 'openai' ? '#eff6ff' : 'transparent', borderRadius: '6px', border: config.provider === 'openai' ? '1px solid #3b82f6' : '1px solid #e2e8f0' }}>
                    <input
                        type="radio"
                        name="vision_provider"
                        value="openai"
                        checked={config.provider === 'openai'}
                        onChange={() => handleChange('provider', 'openai')}
                    />
                    <div style={{ display: 'flex', flexDirection: 'column' }}>
                        <span style={{ fontWeight: 600 }}>OpenAI GPT-4o</span>
                        <span style={{ fontSize: '0.75rem', color: '#64748b' }}>Alta precisión</span>
                    </div>
                </label>
            </div>

            {config.provider === 'gemini' && (
                <div className="stack" style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                    <h4 style={{ margin: '0 0 1rem 0', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span style={{ fontSize: '1.2rem' }}>✨</span> Configuración Gemini
                    </h4>
                    <Input
                        label="Google API Key"
                        type="password"
                        placeholder="AIza..."
                        value={config.gemini_key}
                        onChange={e => handleChange('gemini_key', e.target.value)}
                    />
                    <p className="text-xs text-muted" style={{ marginTop: '-0.5rem' }}>Dejar en blanco para usar la clave del servidor.</p>

                    <Input
                        label="Modelo (Gemini Model)"
                        placeholder="gemini-2.0-flash-exp"
                        value={config.gemini_model}
                        onChange={e => handleChange('gemini_model', e.target.value)}
                    />
                </div>
            )}

            {config.provider === 'openai' && (
                <div className="stack" style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                    <h4 style={{ margin: '0 0 1rem 0', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span style={{ fontSize: '1.2rem' }}>🤖</span> Configuración OpenAI
                    </h4>
                    <Input
                        label="OpenAI API Key"
                        type="password"
                        placeholder="sk-..."
                        value={config.openai_key}
                        onChange={e => handleChange('openai_key', e.target.value)}
                    />
                    <p className="text-xs text-muted" style={{ marginTop: '-0.5rem' }}>Dejar en blanco para usar la clave del servidor.</p>

                    <Input
                        label="Modelo (GPT Model)"
                        placeholder="gpt-4o"
                        value={config.openai_model}
                        onChange={e => handleChange('openai_model', e.target.value)}
                    />
                </div>
            )}

            <div style={{ marginTop: '1rem' }}>
                <Button onClick={handleSave}>Guardar Cambios</Button>
            </div>
            {status && <div className="text-teal text-center text-sm" style={{ marginTop: '1rem' }}>{status}</div>}
        </div>
    );
}


function BotPanel() {
    const [basalConfig, setBasalConfig] = useState({
        enabled: false,
        schedule: [] // [{id, name, time, units}]
    });

    const [botEnabled, setBotEnabled] = useState(true);
    const [loading, setLoading] = useState(true);
    const [status, setStatus] = useState(null);

    // Initial State structure matches backend models/settings.py defaults
    const [premealConfig, setPremealConfig] = useState({
        enabled: true,
        bg_threshold_mgdl: 150,
        delta_threshold_mgdl: 2,
        window_minutes: 60,
        silence_minutes: 90
    });

    const [comboConfig, setComboConfig] = useState({
        enabled: false,
        window_hours: 6,
        delay_minutes: 120,
        silence_minutes: 180
    });

    const [trendConfig, setTrendConfig] = useState({
        enabled: false,
        rise_mgdl_per_min: 2.0,
        drop_mgdl_per_min: -2.0,
        min_delta_total_mgdl: 35,
        window_minutes: 30,
        silence_minutes: 60
    });

    useEffect(() => {
        const params = getCalcParams() || {};
        setBotEnabled(params.bot?.enabled !== false);

        const proactive = params.bot?.proactive || {};

        if (proactive.premeal) setPremealConfig(prev => ({ ...prev, ...proactive.premeal }));
        if (proactive.combo_followup) setComboConfig(prev => ({ ...prev, ...proactive.combo_followup }));
        if (proactive.trend_alert) setTrendConfig(prev => ({ ...prev, ...proactive.trend_alert }));

        // Basal Config Loading
        if (proactive.basal) {
            let b = proactive.basal;
            // Migration catch: if schedule empty but legacy fields exist, create one
            if ((!b.schedule || b.schedule.length === 0) && b.time_local) {
                b = {
                    ...b,
                    schedule: [{
                        id: 'legacy_' + Date.now(),
                        name: 'Basal',
                        time: b.time_local,
                        units: b.expected_units || 0
                    }]
                };
            }
            setBasalConfig(prev => ({ ...prev, ...b }));
        }

        setLoading(false);
    }, []);

    const handlePremealChange = (field, value) => {
        // Allow empty string for better UX (prevent 0 stuck)
        if (field === 'enabled') {
            setPremealConfig(prev => ({ ...prev, [field]: value }));
        } else {
            setPremealConfig(prev => ({ ...prev, [field]: value }));
        }
    };

    const handleComboChange = (field, value) => {
        if (field === 'enabled') {
            setComboConfig(prev => ({ ...prev, [field]: value }));
        } else {
            setComboConfig(prev => ({ ...prev, [field]: value }));
        }
    };

    const handleTrendChange = (field, value) => {
        if (field === 'enabled') {
            setTrendConfig(prev => ({ ...prev, [field]: value }));
        } else {
            setTrendConfig(prev => ({ ...prev, [field]: value }));
        }
    };

    // Basal Handlers
    const handleBasalChange = (field, value) => {
        setBasalConfig(prev => ({ ...prev, [field]: value }));
    };

    const addBasalSchedule = () => {
        setBasalConfig(prev => ({
            ...prev,
            schedule: [...(prev.schedule || []), { id: Date.now().toString(), name: 'Dosis', time: '22:00', units: '' }]
        }));
    };

    const updateBasalSchedule = (idx, field, value) => {
        setBasalConfig(prev => {
            const copy = [...(prev.schedule || [])];
            copy[idx] = { ...copy[idx], [field]: value };
            return { ...prev, schedule: copy };
        });
    };

    const removeBasalSchedule = (idx) => {
        setBasalConfig(prev => {
            const copy = [...(prev.schedule || [])];
            copy.splice(idx, 1);
            return { ...prev, schedule: copy };
        });
    };

    const handleSave = () => {
        const current = getCalcParams() || {};

        // Sanitize / Parse numbers before saving
        const pInt = (v) => parseInt(v) || 0;
        const pFloat = (v) => parseFloat(v) || 0;

        const cleanPremeal = {
            ...premealConfig,
            bg_threshold_mgdl: pInt(premealConfig.bg_threshold_mgdl),
            delta_threshold_mgdl: pInt(premealConfig.delta_threshold_mgdl),
            window_minutes: pInt(premealConfig.window_minutes),
            silence_minutes: pInt(premealConfig.silence_minutes)
        };

        const cleanCombo = {
            ...comboConfig,
            delay_minutes: pInt(comboConfig.delay_minutes),
            window_hours: pInt(comboConfig.window_hours),
            silence_minutes: pInt(comboConfig.silence_minutes)
        };

        const cleanTrend = {
            ...trendConfig,
            rise_mgdl_per_min: pFloat(trendConfig.rise_mgdl_per_min),
            drop_mgdl_per_min: pFloat(trendConfig.drop_mgdl_per_min),
            min_delta_total_mgdl: pInt(trendConfig.min_delta_total_mgdl),
            window_minutes: pInt(trendConfig.window_minutes),
            silence_minutes: pInt(trendConfig.silence_minutes)
        };

        const cleanBasal = {
            ...basalConfig,
            schedule: (basalConfig.schedule || []).map(s => ({
                ...s,
                units: pFloat(s.units)
            }))
        };

        const newParams = {
            ...current,
            bot: {
                ...(current.bot || {}),
                enabled: botEnabled,
                proactive: {
                    ...(current.bot?.proactive || {}),
                    premeal: cleanPremeal,
                    combo_followup: cleanCombo,
                    trend_alert: cleanTrend,
                    basal: cleanBasal
                }
            }
        };
        saveCalcParams(newParams);

        // Update local state to reflect cleaned values (optional, but good for consistency)
        setPremealConfig(cleanPremeal);
        setComboConfig(cleanCombo);
        setTrendConfig(cleanTrend);
        setBasalConfig(cleanBasal);

        setStatus("✅ Configuración de Bot guardada.");
        setTimeout(() => setStatus(null), 3000);
    };

    if (loading) return <div className="p-4 text-center">Cargando Bot...</div>;

    return (
        <div className="stack">
            <h3 style={{ marginTop: 0 }}>Bot / Proactivo</h3>
            <p className="text-muted text-sm">
                Configura los comportamientos proactivos del asistente.
            </p>

            {/* MASTER SWITCH */}
            <div style={{ background: '#fff', padding: '1rem', borderRadius: '8px', border: '1px solid #cbd5e1', marginBottom: '1.5rem', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.8rem', fontWeight: 700, fontSize: '1.1rem', cursor: 'pointer', color: botEnabled ? '#166534' : '#64748b' }}>
                    <input
                        type="checkbox"
                        checked={botEnabled}
                        onChange={e => setBotEnabled(e.target.checked)}
                        style={{ width: '1.4rem', height: '1.4rem' }}
                    />
                    {botEnabled ? "🟢 Bot Activado" : "🔴 Bot Desactivado"}
                </label>
            </div>

            {/* BASAL SECTION */}
            <div style={{ background: '#f8fafc', padding: '1.2rem', borderRadius: '12px', border: '1px solid #e2e8f0', marginBottom: '1.5rem', boxShadow: '0 1px 2px rgba(0,0,0,0.03)' }}>
                <h4 style={{ margin: '0 0 1rem 0', color: '#334155', fontSize: '1.1rem', fontWeight: 600 }}>💉 Recordatorio Basal (Lenta)</h4>

                <label style={{ display: 'flex', alignItems: 'center', gap: '0.8rem', fontWeight: 600, color: basalConfig.enabled ? '#0f172a' : '#64748b', cursor: 'pointer', marginBottom: '1.2rem', padding: '0.5rem', background: basalConfig.enabled ? '#ffffff' : 'transparent', borderRadius: '8px', border: basalConfig.enabled ? '1px solid #cbd5e1' : '1px solid transparent' }}>
                    <input
                        type="checkbox"
                        checked={basalConfig.enabled}
                        onChange={e => handleBasalChange('enabled', e.target.checked)}
                        style={{ width: '1.3rem', height: '1.3rem', accentColor: '#3b82f6' }}
                    />
                    Activar Recordatorios
                </label>

                {basalConfig.enabled && (
                    <div className="stack" style={{ gap: '0.5rem' }}>
                        {/* Headers Row */}
                        {(basalConfig.schedule || []).length > 0 && (
                            <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 120px 90px auto', gap: '0.8rem', padding: '0 0.5rem', fontSize: '0.8rem', color: '#64748b', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                                <div>Nombre</div>
                                <div>Hora</div>
                                <div>Dosis</div>
                                <div></div>
                            </div>
                        )}

                        {/* List Items */}
                        {(basalConfig.schedule || []).map((item, idx) => (
                            <div key={item.id || idx} style={{
                                display: 'grid',
                                gridTemplateColumns: '1.5fr 120px 90px auto',
                                gap: '0.8rem',
                                alignItems: 'center',
                                background: 'white',
                                padding: '0.8rem',
                                borderRadius: '10px',
                                border: '1px solid #cbd5e1',
                                boxShadow: '0 1px 2px rgba(0,0,0,0.03)'
                            }}>
                                {/* Name */}
                                <div style={{ display: 'flex', flexDirection: 'column' }}>
                                    <input
                                        type="text"
                                        value={item.name}
                                        onChange={e => updateBasalSchedule(idx, 'name', e.target.value)}
                                        placeholder="Nombre..."
                                        style={{ width: '100%', padding: '0.6rem', borderRadius: '6px', border: '1px solid #e2e8f0', fontSize: '0.95rem' }}
                                    />
                                </div>

                                {/* Time */}
                                <div style={{ display: 'flex', flexDirection: 'column' }}>
                                    <input
                                        type="time"
                                        value={item.time}
                                        onChange={e => updateBasalSchedule(idx, 'time', e.target.value)}
                                        style={{ width: '100%', padding: '0.6rem', borderRadius: '6px', border: '1px solid #e2e8f0', fontSize: '0.95rem', textAlign: 'center' }}
                                    />
                                </div>

                                {/* Units */}
                                <div style={{ display: 'flex', flexDirection: 'column' }}>
                                    <input
                                        type="number"
                                        inputMode="decimal"
                                        value={item.units}
                                        onChange={e => updateBasalSchedule(idx, 'units', parseFloat(e.target.value))}
                                        placeholder="0"
                                        style={{ width: '100%', padding: '0.6rem', borderRadius: '6px', border: '1px solid #e2e8f0', fontSize: '1rem', fontWeight: 700, textAlign: 'center', color: '#0369a1' }}
                                    />
                                </div>

                                {/* Delete */}
                                <button
                                    onClick={() => removeBasalSchedule(idx)}
                                    title="Eliminar"
                                    style={{
                                        color: '#ef4444',
                                        border: 'none',
                                        background: '#fee2e2',
                                        cursor: 'pointer',
                                        width: '32px',
                                        height: '32px',
                                        borderRadius: '8px',
                                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                                        transition: 'background 0.2s'
                                    }}
                                >
                                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path></svg>
                                </button>
                            </div>
                        ))}

                        <div style={{ marginTop: '0.5rem', display: 'flex', justifyContent: 'center' }}>
                            <Button variant="secondary" onClick={addBasalSchedule} style={{ width: '100%', borderStyle: 'dashed', borderColor: '#94a3b8', color: '#475569' }}>
                                + Añadir Dosis
                            </Button>
                        </div>
                    </div>
                )}
            </div>

            {/* PREMEAL SECTION */}
            <div style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0', marginBottom: '1rem' }}>
                <h4 style={{ margin: '0 0 1rem 0', color: '#334155' }}>🥣 Aviso Pre-comida (Premeal)</h4>

                <label style={{ display: 'flex', alignItems: 'center', gap: '0.8rem', fontWeight: 600, color: premealConfig.enabled ? '#0f172a' : '#64748b', cursor: 'pointer', marginBottom: '1rem' }}>
                    <input
                        type="checkbox"
                        checked={premealConfig.enabled}
                        onChange={e => handlePremealChange('enabled', e.target.checked)}
                        style={{ width: '1.2rem', height: '1.2rem' }}
                    />
                    Activar
                </label>

                {premealConfig.enabled && (
                    <div className="stack" style={{ gap: '1rem' }}>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                            <Input
                                label="Umbral Glucosa (mg/dL)"
                                type="number"
                                value={premealConfig.bg_threshold_mgdl}
                                onChange={e => handlePremealChange('bg_threshold_mgdl', e.target.value)}
                                placeholder="150"
                            />
                            <Input
                                label="Umbral Delta (+mg/dL)"
                                type="number"
                                value={premealConfig.delta_threshold_mgdl}
                                onChange={e => handlePremealChange('delta_threshold_mgdl', e.target.value)}
                                placeholder="2"
                            />
                        </div>
                        <p className="text-xs text-muted" style={{ marginTop: '-0.5rem' }}>
                            Se activa si Glucosa {'>'} {premealConfig.bg_threshold_mgdl} Y Delta {'>'} +{premealConfig.delta_threshold_mgdl}.
                        </p>

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                            <Input
                                label="Ventana Análisis (min)"
                                type="number"
                                value={premealConfig.window_minutes}
                                onChange={e => handlePremealChange('window_minutes', e.target.value)}
                            />
                            <Input
                                label="Silenciar tras aviso (min)"
                                type="number"
                                value={premealConfig.silence_minutes}
                                onChange={e => handlePremealChange('silence_minutes', e.target.value)}
                            />
                        </div>
                    </div>
                )}
            </div>

            {/* TREND ALERT SECTION */}
            <div style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0', marginBottom: '1rem' }}>
                <h4 style={{ margin: '0 0 1rem 0', color: '#334155' }}>📈 Alertas Tendencia (Sin Comida)</h4>

                <label style={{ display: 'flex', alignItems: 'center', gap: '0.8rem', fontWeight: 600, color: trendConfig.enabled ? '#0f172a' : '#64748b', cursor: 'pointer', marginBottom: '1rem' }}>
                    <input
                        type="checkbox"
                        checked={trendConfig.enabled}
                        onChange={e => handleTrendChange('enabled', e.target.checked)}
                        style={{ width: '1.2rem', height: '1.2rem' }}
                    />
                    Activar
                </label>

                {trendConfig.enabled && (
                    <div className="stack" style={{ gap: '1rem' }}>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                            <Input
                                label="Velocidad Subida (mg/dL/min)"
                                type="number"
                                step="0.1"
                                value={trendConfig.rise_mgdl_per_min}
                                onChange={e => handleTrendChange('rise_mgdl_per_min', e.target.value)}
                            />
                            <Input
                                label="Velocidad Bajada (mg/dL/min)"
                                type="number"
                                step="0.1"
                                value={trendConfig.drop_mgdl_per_min}
                                onChange={e => handleTrendChange('drop_mgdl_per_min', e.target.value)}
                            />
                        </div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                            <Input
                                label="Cambio Total Mínimo (mg/dL)"
                                type="number"
                                value={trendConfig.min_delta_total_mgdl}
                                onChange={e => handleTrendChange('min_delta_total_mgdl', e.target.value)}
                            />
                            <Input
                                label="Ventana Análisis (min)"
                                type="number"
                                value={trendConfig.window_minutes}
                                onChange={e => handleTrendChange('window_minutes', e.target.value)}
                            />
                        </div>
                        <Input
                            label="Silenciar / Cooldown (min)"
                            type="number"
                            value={trendConfig.silence_minutes}
                            onChange={e => handleTrendChange('silence_minutes', e.target.value)}
                        />
                    </div>
                )}
            </div>


            {/* COMBO FOLLOWUP SECTION */}
            <div style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0', marginBottom: '1rem' }}>
                <h4 style={{ margin: '0 0 1rem 0', color: '#334155' }}>🔁 Combo Follow-up</h4>
                <p className="text-xs text-muted" style={{ marginBottom: '1rem' }}>
                    Pregunta si quieres registrar la 2ª parte de un bolo extendido si ha pasado tiempo.
                </p>

                <label style={{ display: 'flex', alignItems: 'center', gap: '0.8rem', fontWeight: 600, color: comboConfig.enabled ? '#0f172a' : '#64748b', cursor: 'pointer', marginBottom: '1rem' }}>
                    <input
                        type="checkbox"
                        checked={comboConfig.enabled}
                        onChange={e => handleComboChange('enabled', e.target.checked)}
                        style={{ width: '1.2rem', height: '1.2rem' }}
                    />
                    Activar Recordatorio 2ª Parte
                </label>

                {comboConfig.enabled && (
                    <div className="stack" style={{ gap: '1rem' }}>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                            <Input
                                label="Esperar tras bolo (min)"
                                type="number"
                                min="5"
                                max="480"
                                value={comboConfig.delay_minutes}
                                onChange={e => handleComboChange('delay_minutes', e.target.value)}
                                placeholder="120"
                            />
                            <Input
                                label="Mirar últimos (horas)"
                                type="number"
                                min="1"
                                max="24"
                                value={comboConfig.window_hours}
                                onChange={e => handleComboChange('window_hours', e.target.value)}
                            />
                        </div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                            <Input
                                label="Silenciar / Cooldown (min)"
                                type="number"
                                min="0"
                                max="720"
                                value={comboConfig.silence_minutes}
                                onChange={e => handleComboChange('silence_minutes', e.target.value)}
                            />
                        </div>
                    </div>
                )}
            </div>

            <div style={{ marginTop: '0.5rem' }}>
                <Button onClick={handleSave}>Guardar Configuración Bot</Button>
            </div>
            {status && <div className="text-teal text-center text-sm" style={{ marginTop: '1rem' }}>{status}</div>}
        </div>
    );
}




function SchedulePanel({ settings, onChange }) {
    const s = settings.schedule || { breakfast_start_hour: 5, lunch_start_hour: 13, dinner_start_hour: 20 };

    const update = (field, val) => {
        const num = parseInt(val) || 0;
        // Ensure within 0-23
        const clamped = Math.min(23, Math.max(0, num));

        onChange(prev => ({
            ...prev,
            schedule: { ...(prev.schedule || s), [field]: clamped }
        }));
    };

    return (
        <div style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0', marginBottom: '1.5rem' }}>
            <h4 style={{ marginTop: 0, marginBottom: '0.8rem', color: '#334155', fontSize: '1rem' }}>⏰ Horarios de Comidas (Inicio)</h4>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.8rem' }}>
                <Input label="Desayuno (H)" type="number" value={s.breakfast_start_hour} onChange={e => update('breakfast_start_hour', e.target.value)} />
                <Input label="Comida (H)" type="number" value={s.lunch_start_hour} onChange={e => update('lunch_start_hour', e.target.value)} />
                <Input label="Cena (H)" type="number" value={s.dinner_start_hour} onChange={e => update('dinner_start_hour', e.target.value)} />
            </div>
            <p className="text-xs text-muted" style={{ marginTop: '0.5rem' }}>
                Determina qué perfil (ICR/ISF) se aplica según la hora.
            </p>
        </div>
    );
}

function LabsPanel() {
    const [enabled, setEnabled] = React.useState(false);
    const [confidence, setConfidence] = React.useState(0);
    const [logs, setLogs] = React.useState([]);
    const [loading, setLoading] = React.useState(true);

    React.useEffect(() => {
        // Load settings from Backend (via Store/API)
        import('../modules/core/store').then(({ getCalcParams }) => {
            const params = getCalcParams();
            if (params && params.labs) {
                setEnabled(params.labs.shadow_mode_enabled || false);
            }
            setLoading(false);
        });

        // Load Logs
        import('../lib/api').then(({ getShadowLogs }) => {
            getShadowLogs().then(data => {
                // Map backend format to UI format if needed
                // Backend: { created_at, scenario, suggestion, is_better, improvement_pct ... }
                // UI expects: { id, date, meal, suggestion, result, status }
                if (Array.isArray(data)) {
                    const mapped = data.map(log => ({
                        id: log.id,
                        date: new Date(log.created_at).toLocaleString(),
                        meal: log.meal_name || 'Comida',
                        suggestion: log.scenario,
                        result: log.is_better ? `Mejora ${(log.improvement_pct || 0).toFixed(0)}%` : 'Sin mejora',
                        status: log.is_better ? 'success' : 'neutral'
                    }));
                    setLogs(mapped);

                    // Naive confidence calc
                    if (mapped.length > 5) {
                        const successCount = mapped.filter(l => l.status === 'success').length;
                        setConfidence(Math.round((successCount / mapped.length) * 100));
                    }
                }
            }).catch(e => console.warn(e));
        });
    }, []);

    const toggle = () => {
        const newVal = !enabled;
        setEnabled(newVal);

        // Save to Backend
        import('../modules/core/store').then(({ getCalcParams, saveCalcParams }) => {
            const current = getCalcParams() || {};
            const newParams = {
                ...current,
                labs: { ...current.labs, shadow_mode_enabled: newVal }
            };
            saveCalcParams(newParams); // This syncs to backend API
        });
    };

    if (loading) return <div className="p-4 text-center text-muted">Cargando Labs...</div>;

    return (
        <div className="stack">
            <h3 style={{ marginTop: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                🧪 Shadow Labs <span style={{ fontSize: '0.7rem', background: '#e0f2fe', color: '#0369a1', padding: '2px 6px', borderRadius: '4px' }}>BETA</span>
            </h3>

            <div style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', padding: '1rem', borderRadius: '8px' }}>
                <div style={{ marginBottom: '1rem' }}>
                    <div style={{ fontWeight: 600, color: '#166534' }}>Análisis Continuo de Absorción</div>
                    <div style={{ fontSize: '0.85rem', color: '#15803d', marginTop: '4px' }}>
                        La IA analiza cada comida en segundo plano para detectar errores de absorción y sugerir mejoras.
                    </div>
                </div>

                {/* Main Content Always Visible */}
                <div style={{ background: 'white', borderRadius: '8px', padding: '1rem', border: '1px solid #e2e8f0' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                        <span style={{ fontSize: '0.9rem', fontWeight: 600 }}>Confianza del Modelo</span>
                        <span style={{ fontWeight: 700, color: confidence > 80 ? '#16a34a' : '#ca8a04' }}>{confidence}%</span>
                    </div>
                    <div style={{ width: '100%', background: '#f1f5f9', height: '8px', borderRadius: '4px', overflow: 'hidden' }}>
                        <div style={{ width: `${confidence}%`, background: confidence > 80 ? '#16a34a' : '#ca8a04', height: '100%' }}></div>
                    </div>
                    <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '6px' }}>
                        {confidence > 80 ? '✅ Fiabilidad alta. Recomendado activar.' : 'Recopilando datos para calibración...'}
                    </div>
                </div>

                <div style={{ marginTop: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#ecfdf5', padding: '0.8rem', borderRadius: '8px', border: '1px solid #6ee7b7' }}>
                    <div style={{ fontSize: '0.9rem', fontWeight: 600, color: '#064e3b' }}>
                        Aplicar Correcciones
                        <div style={{ fontSize: '0.75rem', fontWeight: 400, marginTop: '2px', color: '#047857', opacity: 0.9 }}>
                            Permitir que la IA ajuste la absorción automáticamente en futuros cálculos.
                        </div>
                    </div>
                    <label className="switch" style={{ position: 'relative', display: 'inline-block', width: '40px', height: '24px', flexShrink: 0 }}>
                        <input type="checkbox" checked={enabled} onChange={toggle} style={{ opacity: 0, width: 0, height: 0 }} />
                        <span style={{
                            position: 'absolute', cursor: 'pointer', top: 0, left: 0, right: 0, bottom: 0,
                            backgroundColor: enabled ? '#16a34a' : '#ccc', borderRadius: '34px', transition: '0.4s'
                        }}>
                            <span style={{
                                position: 'absolute', content: "", height: '16px', width: '16px', left: '4px', bottom: '4px',
                                backgroundColor: 'white', borderRadius: '50%', transition: '0.4s',
                                transform: enabled ? 'translateX(16px)' : 'translateX(0)'
                            }}></span>
                        </span>
                    </label>
                </div>

                {enabled && (
                    <div className="fade-in" style={{ marginTop: '0.8rem', fontSize: '0.8rem', color: '#166534', background: '#dcfce7', padding: '0.5rem', borderRadius: '6px' }}>
                        <strong>⚠️ Nota:</strong> Se requiere supervisión. Esta función solo se activará tras 20 comprobaciones seguras consecutivas.
                    </div>
                )}

                <h4 style={{ margin: '1.5rem 0 0.5rem 0', fontSize: '0.9rem', color: '#475569' }}>Historial en la Sombra</h4>
                {logs.length === 0 && (
                    <div style={{ padding: '1rem', textAlign: 'center', color: '#94a3b8', fontSize: '0.85rem', border: '1px dashed #cbd5e1', borderRadius: '6px' }}>
                        ⏳ La IA está analizando tus datos recientes...
                    </div>
                )}
                <div className="stack" style={{ gap: '0.5rem' }}>
                    {logs.map(log => (
                        <div key={log.id} style={{
                            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                            padding: '0.6rem', background: '#f8fafc', borderRadius: '6px', border: '1px solid #e2e8f0', fontSize: '0.85rem'
                        }}>
                            <div>
                                <div style={{ fontWeight: 600 }}>{log.meal} <span style={{ fontWeight: 400, color: '#94a3b8' }}>• {log.date}</span></div>
                                <div style={{ color: '#64748b' }}>{log.suggestion}</div>
                            </div>
                            <div style={{
                                fontWeight: 600,
                                color: log.status === 'success' ? '#16a34a' : '#64748b',
                                fontSize: '0.8rem'
                            }}>
                                {log.result}
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}

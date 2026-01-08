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
    fetchHealth, exportUserData, importUserData, fetchAutosens,
    getSettings, updateSettings, getLearningLogs, testDexcom,
    fetchIngestLogs, getNutritionDraft, discardNutritionDraft
} from '../lib/api';
import { IsfAnalyzer } from '../components/settings/IsfAnalyzer';


export default function SettingsPage() {
    const [activeTab, setActiveTab] = useState('ns'); // 'ns' | 'calc' | 'data' | 'analysis' | 'favs'

    return (
        <>
            <Header title="Ajustes" showBack={true} />
            <main className="page" style={{ paddingBottom: '80px' }}>
                <Card>
                    <div className="tabs" style={{ display: 'flex', borderBottom: '1px solid #e2e8f0', marginBottom: '1rem', overflowX: 'auto' }}>
                        <TabButton label="Nightscout" active={activeTab === 'ns'} onClick={() => setActiveTab('ns')} />
                        <TabButton label="Dexcom" active={activeTab === 'dexcom'} onClick={() => setActiveTab('dexcom')} />
                        <TabButton label="Cálculo" active={activeTab === 'calc'} onClick={() => setActiveTab('calc')} />
                        <TabButton label="IA / Visión" active={activeTab === 'vision'} onClick={() => setActiveTab('vision')} />
                        <TabButton label="Análisis" active={activeTab === 'analysis'} onClick={() => setActiveTab('analysis')} />
                        <TabButton label="Datos" active={activeTab === 'data'} onClick={() => setActiveTab('data')} />
                        <TabButton label="Aprendizaje" active={activeTab === 'labs'} onClick={() => setActiveTab('labs')} />
                        <TabButton label="Bot" active={activeTab === 'bot'} onClick={() => setActiveTab('bot')} />
                        <TabButton label="Logs Ingesta" active={activeTab === 'logs'} onClick={() => setActiveTab('logs')} />
                    </div>

                    {activeTab === 'ns' && <NightscoutPanel />}
                    {activeTab === 'dexcom' && <DexcomPanel />}
                    {activeTab === 'calc' && <CalcParamsPanel />}
                    {activeTab === 'vision' && <VisionPanel />}
                    {activeTab === 'bot' && <BotPanel />}
                    {activeTab === 'analysis' && <IsfAnalyzer />}
                    {activeTab === 'data' && <DataPanel />}
                    {activeTab === 'labs' && <LabsPanel />}
                    {activeTab === 'logs' && <IngestLogsPanel />}
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
    const [filterConfig, setFilterConfig] = useState({
        enabled: false,
        night_start: "23:00",
        night_end: "07:00",
        treatments_lookback_minutes: 120
    });
    const [filterStatus, setFilterStatus] = useState({ msg: '', type: 'neutral' });
    const [savingFilter, setSavingFilter] = useState(false);

    useEffect(() => {
        getNightscoutSecretStatus().then(res => {
            if (res.url) setUrl(res.url);
            setHasSecret(res.has_secret);
        }).catch(err => console.warn(err));

        getSettings().then(res => {
            const nsSettings = res.settings?.nightscout || {};
            setFilterConfig({
                enabled: Boolean(nsSettings.filter_compression),
                night_start: nsSettings.filter_night_start || "23:00",
                night_end: nsSettings.filter_night_end || "07:00",
                treatments_lookback_minutes: nsSettings.treatments_lookback_minutes ?? 120
            });
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

    const handleSaveFilter = async () => {
        setSavingFilter(true);
        setFilterStatus({ msg: 'Guardando...', type: 'neutral' });

        try {
            const current = await getSettings();
            const newSettings = current.settings || {};
            newSettings.nightscout = {
                ...(newSettings.nightscout || {}),
                filter_compression: filterConfig.enabled,
                filter_night_start: filterConfig.night_start,
                filter_night_end: filterConfig.night_end,
                treatments_lookback_minutes: Number(filterConfig.treatments_lookback_minutes || 120)
            };

            await updateSettings({ ...newSettings, version: current.version });
            setFilterStatus({ msg: '✅ Filtro actualizado.', type: 'success' });
        } catch (e) {
            if (e.isConflict) {
                setFilterStatus({ msg: '❌ Conflicto de versión. Recarga e intenta de nuevo.', type: 'error' });
            } else {
                setFilterStatus({ msg: `❌ Error guardando: ${e.message}`, type: 'error' });
            }
        } finally {
            setSavingFilter(false);
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

            <div style={{ marginTop: '1.5rem', padding: '1rem', borderRadius: '12px', border: '1px solid #e2e8f0', background: '#f8fafc' }}>
                <h4 style={{ margin: '0 0 0.5rem 0' }}>Filtro anti-compresión (falsos bajos nocturnos)</h4>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', fontWeight: 600 }}>
                    <input
                        type="checkbox"
                        checked={filterConfig.enabled}
                        onChange={e => setFilterConfig(prev => ({ ...prev, enabled: e.target.checked }))}
                    />
                    Activar filtro
                </label>

                {filterConfig.enabled && (
                    <div className="stack" style={{ marginTop: '0.8rem' }}>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                            <Input
                                label="Inicio noche"
                                type="time"
                                value={filterConfig.night_start}
                                onChange={e => setFilterConfig(prev => ({ ...prev, night_start: e.target.value }))}
                            />
                            <Input
                                label="Fin noche"
                                type="time"
                                value={filterConfig.night_end}
                                onChange={e => setFilterConfig(prev => ({ ...prev, night_end: e.target.value }))}
                            />
                        </div>
                        <Input
                            label="Lookback tratamientos (min)"
                            type="number"
                            min="0"
                            value={filterConfig.treatments_lookback_minutes}
                            onChange={e => setFilterConfig(prev => ({ ...prev, treatments_lookback_minutes: e.target.value }))}
                        />
                        <p className="text-muted text-sm" style={{ margin: 0 }}>
                            Ajusta cuánto tiempo atrás se consideran tratamientos recientes para evitar falsos positivos.
                        </p>
                    </div>
                )}

                <Button onClick={handleSaveFilter} disabled={savingFilter} style={{ marginTop: '1rem' }}>
                    {savingFilter ? 'Guardando...' : 'Guardar Ajustes'}
                </Button>
                {filterStatus.msg && (
                    <div style={{
                        marginTop: '0.75rem',
                        padding: '0.6rem',
                        borderRadius: '8px',
                        background: filterStatus.type === 'error' ? '#fee2e2' : (filterStatus.type === 'success' ? '#dcfce7' : '#f1f5f9'),
                        color: filterStatus.type === 'error' ? '#ef4444' : (filterStatus.type === 'success' ? '#166534' : '#334155'),
                        fontWeight: 600
                    }}>
                        {filterStatus.msg}
                    </div>
                )}
            </div>
        </div>
    );
}

function DexcomPanel() {
    const [config, setConfig] = useState({
        enabled: false,
        username: '',
        password: '',
        region: 'ous' // 'us', 'ous'
    });
    const [loading, setLoading] = useState(true);
    const [status, setStatus] = useState(null);
    const [version, setVersion] = useState(0);

    // Fetch existing settings
    useEffect(() => {
        getSettings().then(res => {
            if (res.settings && res.settings.dexcom) {
                setConfig({
                    enabled: res.settings.dexcom.enabled || false,
                    username: res.settings.dexcom.username || '',
                    password: '', // Don't fetch password back for security, just blank
                    region: res.settings.dexcom.region || 'ous'
                });
            }
            if (res.version) setVersion(res.version);
            setLoading(false);
        }).catch(e => {
            console.warn(e);
            setLoading(false);
        });
    }, []);

    const handleChange = (field, value) => {
        setConfig(prev => ({ ...prev, [field]: value }));
    };

    const handleSave = async () => {
        setStatus({ msg: 'Guardando...', type: 'neutral' });

        try {
            const current = await getSettings();
            const newSettings = current.settings || {};
            newSettings.dexcom = {
                enabled: config.enabled,
                username: config.username,
                region: config.region
            };
            if (config.password) {
                newSettings.dexcom.password = config.password;
            }

            // Perform Save with VERSION
            const res = await updateSettings({ ...newSettings, version: current.version });
            if (res.version) setVersion(res.version);

            setStatus({ msg: '✅ Configuración Dexcom Guardada.', type: 'success' });

        } catch (e) {
            if (e.isConflict) {
                setStatus({ msg: `❌ Error de versión (Conflicto). Recargue la página e intente de nuevo.`, type: 'error' });
            } else {
                setStatus({ msg: `❌ Error: ${e.message}`, type: 'error' });
            }
        }
    };

    if (loading) return <div>Cargando...</div>;

    return (
        <div className="stack">
            <h3 style={{ marginTop: 0 }}>Conexión Dexcom Share</h3>
            <p className="text-muted text-sm">
                Conecta directamente con Dexcom para obtener valores de glucosa sin depender de Nightscout (lectura).
            </p>

            <div style={{ background: '#f0f9ff', padding: '1rem', borderRadius: '8px', border: '1px solid #bae6fd', marginBottom: '1rem' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.8rem', fontWeight: 600, color: '#0369a1', cursor: 'pointer' }}>
                    <input
                        type="checkbox"
                        checked={config.enabled}
                        onChange={e => handleChange('enabled', e.target.checked)}
                        style={{ width: '1.2rem', height: '1.2rem' }}
                    />
                    Habilitar Dexcom Share
                </label>
            </div>

            {config.enabled && (
                <div className="stack fade-in">
                    <Input
                        label="Usuario Dexcom"
                        placeholder="+34..."
                        value={config.username}
                        onChange={e => handleChange('username', e.target.value)}
                    />
                    <Input
                        label="Contraseña"
                        type="password"
                        placeholder={config.password ? "••••••" : "(Sin cambios)"}
                        value={config.password}
                        onChange={e => handleChange('password', e.target.value)}
                    />

                    <div className="form-group">
                        <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 600 }}>Región</label>
                        <select
                            value={config.region}
                            onChange={e => handleChange('region', e.target.value)}
                            style={{ width: '100%', padding: '0.8rem', borderRadius: '8px', border: '1px solid #cbd5e1' }}
                        >
                            <option value="ous">Europa / Mundo (Fuera de EEUU)</option>
                            <option value="us">Estados Unidos</option>
                        </select>
                    </div>

                    <div style={{ display: 'flex', gap: '8px', marginTop: '1rem' }}>
                        <Button
                            variant="secondary"
                            onClick={async () => {
                                setStatus({ msg: 'Probando conexión...', type: 'neutral' });
                                try {
                                    const data = await testDexcom({
                                        username: config.username,
                                        password: config.password,
                                        region: config.region
                                    });
                                    if (data.success) {
                                        setStatus({ msg: `✅ ${data.message}`, type: 'success' });
                                    } else {
                                        setStatus({ msg: `❌ ${data.message}`, type: 'error' });
                                    }
                                } catch (e) {
                                    setStatus({ msg: `❌ Error: ${e.message}`, type: 'error' });
                                }
                            }}
                        >
                            📡 Probar Conexión
                        </Button>
                    </div>
                </div>
            )}

            <div className="card-section" style={{ marginTop: '1.5rem', padding: '1rem', background: '#fff1f2', borderRadius: '8px', border: '1px solid #fda4af' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.8rem', fontWeight: 600, color: '#9f1239', cursor: 'pointer' }}>
                    <input
                        type="checkbox"
                        checked={!config.enabled}
                        onChange={e => handleChange('enabled', !e.target.checked)}
                        style={{ width: '1.2rem', height: '1.2rem' }}
                    />
                    Bypass de Emergencia (Usar solo Nightscout)
                </label>
                <div style={{ fontSize: '0.8rem', color: '#881337', marginTop: '4px', marginLeft: '2rem' }}>
                    Si Dexcom Share falla, activa esto para forzar el uso de Nightscout como fuente de datos.
                </div>
            </div>

            <Button onClick={handleSave} style={{ marginTop: '1rem' }}>Guardar Dexcom</Button>

            {status && status.msg && (
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
        techne: { enabled: false, max_step_change: 0.5, safety_iob_threshold: 1.5 },
        warsaw: { enabled: true, trigger_threshold_kcal: 300, safety_factor: 0.1, safety_factor_dual: 0.2 },
        autosens: { enabled: true, min_ratio: 0.7, max_ratio: 1.2 },
        calculator: { subtract_fiber: false, fiber_factor: 0.5 },
        timezone: 'Europe/Madrid'
    };

    const [params, setParams] = useState(defaults);
    const [splitParams, setSplitParams] = useState(getSplitSettings());
    const [slot, setSlot] = useState('breakfast');
    const [status, setStatus] = useState(null);
    const [autosensResult, setAutosensResult] = useState(null);

    useEffect(() => {
        const p = getCalcParams();
        if (p) {
            // Deep merge for techne to ensure it exists
            const merged = {
                ...defaults,
                ...p,
                techne: { ...defaults.techne, ...(p.techne || {}) },
                warsaw: { ...defaults.warsaw, ...(p.warsaw || {}) },
                autosens: { ...defaults.autosens, ...(p.autosens || {}) },
                calculator: { ...defaults.calculator, ...(p.calculator || {}) }
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

        if (clean.calculator) {
            clean.calculator.fiber_factor = p(clean.calculator.fiber_factor);
        }

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

            <div style={{ marginTop: '1rem', padding: '1rem', background: '#fdf4ff', borderRadius: '8px', border: '1px solid #f0abfc' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.8rem', fontWeight: 600, color: '#86198f', cursor: 'pointer' }}>
                    <input
                        type="checkbox"
                        checked={params.calculator?.subtract_fiber}
                        onChange={e => setParams(prev => ({ ...prev, calculator: { ...prev.calculator, subtract_fiber: e.target.checked } }))}
                        style={{ width: '1.2rem', height: '1.2rem' }}
                    />
                    Restar Fibra (Net Carbs)
                </label>

                {params.calculator?.subtract_fiber && (
                    <div className="stack" style={{ gap: '0.8rem', marginTop: '0.5rem' }}>
                        <div style={{ margin: '0.5rem 0 0.5rem 0', fontSize: '0.8rem', color: '#701a75' }}>
                            Si activado: <strong>Carbos - (Fibra * Factor)</strong> cuando Fibra {'>'} 5g.
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                            <Input
                                label="Factor de Resta (0.5 = 50%)"
                                type="text"
                                inputMode="decimal"
                                placeholder="0.5"
                                value={params.calculator.fiber_factor}
                                onChange={e => {
                                    // Allow typing freely (text), normalize on Save later
                                    // Just ensure dot format for state consistency
                                    const val = e.target.value.replace(',', '.');
                                    setParams(prev => ({ ...prev, calculator: { ...prev.calculator, fiber_factor: val } }));
                                }}
                                onFocus={(e) => e.target.select()}
                            />
                        </div>
                        <div style={{ fontSize: '0.75rem', color: '#a21caf' }}>
                            💡 <strong>Ejemplo:</strong> 30g Carbos, 10g Fibra. <br />
                            Con factor 0.5: Resta 5g. <br />
                            Con factor 1.0 (Net): Resta 10g.
                        </div>
                    </div>
                )}
                {!params.calculator?.subtract_fiber && (
                    <div style={{ margin: '0.5rem 0 0 2rem', fontSize: '0.8rem', color: '#701a75' }}>
                        Activa para descontar fibra de los carbohidratos totales.
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
                        <div style={{ marginTop: '0.5rem', borderTop: '1px solid #bbf7d0', paddingTop: '0.5rem' }}>
                            {!autosensResult ? (
                                <Button variant="ghost" style={{ fontSize: '0.8rem', padding: '0.4rem', background: '#dcfce7', color: '#166534' }} onClick={async () => {
                                    try {
                                        const res = await fetchAutosens();
                                        setAutosensResult(res);
                                    } catch (e) {
                                        alert("Error: " + e.message);
                                    }
                                }}>
                                    📡 Consultar Estado Actual (Live)
                                </Button>
                            ) : (
                                <div style={{ fontSize: '0.9rem', color: '#14532d' }}>
                                    <div><strong>Ratio Actual:</strong> {autosensResult.ratio.toFixed(2)}x</div>
                                    <div style={{ fontSize: '0.8rem', opacity: 0.8 }}>{autosensResult.reason}</div>
                                </div>
                            )}
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
    return (
        <div style={{ textAlign: 'center' }}>
            <p style={{ color: '#64748b', marginBottom: '1rem' }}>
                Revisa el estado de todos los servicios: IA, Autosens, Nightscout, etc.
            </p>
            <button
                onClick={() => window.location.hash = '#/status'}
                style={{
                    background: '#0f172a',
                    color: '#22d3ee',
                    padding: '0.8rem 1.5rem',
                    borderRadius: '8px',
                    border: 'none',
                    fontWeight: 700,
                    cursor: 'pointer',
                    width: '100%',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px'
                }}
            >
                🖥️ Abrir Dashboard de Estado
            </button>
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
                        {/* List Items (Mobile Card Style) */}
                        {(basalConfig.schedule || []).map((item, idx) => (
                            <div key={item.id || idx} style={{
                                background: 'white',
                                padding: '1rem',
                                borderRadius: '12px',
                                border: '1px solid #cbd5e1',
                                marginBottom: '0.8rem',
                                boxShadow: '0 1px 3px rgba(0,0,0,0.05)'
                            }}>
                                {/* Row 1: Name */}
                                <div style={{ marginBottom: '0.8rem' }}>
                                    <label style={{ fontSize: '0.75rem', fontWeight: 700, color: '#64748b', display: 'block', marginBottom: '0.3rem', textTransform: 'uppercase' }}>
                                        Nombre de la Insulina
                                    </label>
                                    <input
                                        type="text"
                                        value={item.name}
                                        onChange={e => updateBasalSchedule(idx, 'name', e.target.value)}
                                        placeholder="Ej. Lantus / Toujeo / Levemir"
                                        style={{
                                            width: '100%',
                                            padding: '0.7rem',
                                            borderRadius: '8px',
                                            border: '1px solid #e2e8f0',
                                            fontSize: '1rem',
                                            color: '#1e293b'
                                        }}
                                    />
                                </div>

                                {/* Row 2: Time & Units & Delete */}
                                <div style={{ display: 'flex', gap: '1rem', alignItems: 'flex-end' }}>
                                    <div style={{ flex: 1 }}>
                                        <label style={{ fontSize: '0.75rem', fontWeight: 700, color: '#64748b', display: 'block', marginBottom: '0.3rem', textTransform: 'uppercase' }}>
                                            Hora
                                        </label>
                                        <input
                                            type="time"
                                            value={item.time}
                                            onChange={e => updateBasalSchedule(idx, 'time', e.target.value)}
                                            style={{
                                                width: '100%',
                                                padding: '0.7rem',
                                                borderRadius: '8px',
                                                border: '1px solid #e2e8f0',
                                                fontSize: '1rem',
                                                textAlign: 'center',
                                                color: '#1e293b'
                                            }}
                                        />
                                    </div>

                                    <div style={{ flex: 0.8 }}>
                                        <label style={{ fontSize: '0.75rem', fontWeight: 700, color: '#64748b', display: 'block', marginBottom: '0.3rem', textTransform: 'uppercase' }}>
                                            Dosis (U)
                                        </label>
                                        <input
                                            type="number"
                                            inputMode="decimal"
                                            value={item.units}
                                            onChange={e => updateBasalSchedule(idx, 'units', e.target.value)}
                                            placeholder="0"
                                            style={{
                                                width: '100%',
                                                padding: '0.7rem',
                                                borderRadius: '8px',
                                                border: '1px solid #e2e8f0',
                                                fontSize: '1.1rem',
                                                fontWeight: 700,
                                                textAlign: 'center',
                                                color: '#0369a1'
                                            }}
                                        />
                                    </div>

                                    <button
                                        onClick={() => removeBasalSchedule(idx)}
                                        title="Eliminar"
                                        style={{
                                            marginBottom: '2px',
                                            color: '#ef4444',
                                            border: 'none',
                                            background: '#fee2e2',
                                            cursor: 'pointer',
                                            width: '42px',
                                            height: '42px',
                                            borderRadius: '10px',
                                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                                            transition: 'background 0.2s',
                                            flexShrink: 0
                                        }}
                                    >
                                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path></svg>
                                    </button>
                                </div>
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
        if (val === '') {
            onChange(prev => ({
                ...prev,
                schedule: { ...(prev.schedule || s), [field]: '' }
            }));
            return;
        }

        const num = parseInt(val);
        if (!isNaN(num)) {
            // Clamping 0-23
            const clamped = Math.min(23, Math.max(0, num));
            onChange(prev => ({
                ...prev,
                schedule: { ...(prev.schedule || s), [field]: clamped }
            }));
        }
    };

    const inputStyle = {
        width: '100%',
        padding: '0.6rem',
        borderRadius: '8px',
        border: '1px solid #cbd5e1',
        fontSize: '1.2rem',
        textAlign: 'center',
        fontWeight: 700,
        color: '#334155',
        height: '46px' // Fixed height for alignment
    };

    const labelStyle = {
        display: 'block',
        marginBottom: '0.5rem',
        fontWeight: 600,
        fontSize: '0.8rem',
        color: '#64748b',
        textTransform: 'uppercase',
        textAlign: 'center'
    };

    return (
        <div style={{ background: 'white', padding: '1rem', borderRadius: '12px', border: '1px solid #e2e8f0', marginBottom: '1.5rem', boxShadow: '0 2px 4px rgba(0,0,0,0.02)' }}>
            <h4 style={{ marginTop: 0, marginBottom: '1rem', color: '#334155', fontSize: '1rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                ⏰ Horarios y Zona
            </h4>

            <div style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', marginBottom: '0.4rem', fontWeight: 600, fontSize: '0.8rem', color: '#64748b', textTransform: 'uppercase' }}>
                    Zona Horaria
                </label>
                <select
                    value={settings.timezone || 'Europe/Madrid'}
                    onChange={e => onChange(prev => ({ ...prev, timezone: e.target.value }))}
                    style={{
                        width: '100%',
                        padding: '0.6rem',
                        borderRadius: '8px',
                        border: '1px solid #cbd5e1',
                        fontSize: '1rem',
                        background: 'white'
                    }}
                >
                    <option value="Europe/Madrid">Europe/Madrid (España Peninsular)</option>
                    <option value="Atlantic/Canary">Atlantic/Canary (Canarias)</option>
                    <option value="Europe/London">Europe/London (UK / Portugal)</option>
                    <option value="Europe/Paris">Europe/Paris (Central Europe)</option>
                    <option value="America/New_York">America/New_York (US East)</option>
                    <option value="America/Chicago">America/Chicago (US Central)</option>
                    <option value="America/Los_Angeles">America/Los_Angeles (US West)</option>
                    <option value="UTC">UTC (Universal)</option>
                </select>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1rem' }}>
                <div>
                    <label style={labelStyle}>Desayuno</label>
                    <input
                        type="number"
                        value={s.breakfast_start_hour}
                        onChange={e => update('breakfast_start_hour', e.target.value)}
                        style={inputStyle}
                    />
                </div>
                <div>
                    <label style={labelStyle}>Comida</label>
                    <input
                        type="number"
                        value={s.lunch_start_hour}
                        onChange={e => update('lunch_start_hour', e.target.value)}
                        style={inputStyle}
                    />
                </div>
                <div>
                    <label style={labelStyle}>Cena</label>
                    <input
                        type="number"
                        value={s.dinner_start_hour}
                        onChange={e => update('dinner_start_hour', e.target.value)}
                        style={inputStyle}
                    />
                </div>
            </div>
            <p className="text-xs text-muted" style={{ marginTop: '0.8rem', textAlign: 'center' }}>
                Define la hora de inicio para aplicar el perfil correspondiente.
            </p>
        </div>
    );
}

function LabsPanel() {
    const [response, setResponse] = useState(null);
    const [logs, setLogs] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const loadData = async () => {
            try {
                const [s, l] = await Promise.all([
                    getSettings(),
                    getLearningLogs(5)
                ]);
                setResponse(s || {});
                setLogs(l || []);
            } catch (e) {
                console.error(e);
            } finally {
                setLoading(false);
            }
        };
        loadData();
    }, []);

    const inner = response?.settings || {};
    const version = response?.version;

    const handleUpdateAutonomy = async (enabled) => {
        if (!response) return;

        try {
            // 1. Optimistic
            const newInner = {
                ...inner,
                learning: { ...inner.learning, auto_apply_safe: enabled }
            };
            setResponse(prev => ({ ...prev, settings: newInner }));

            // 2. Payload
            const payload = {
                ...newInner,
                version: version
            };

            await updateSettings(payload);

            // 3. Confirm
            const fresh = await getSettings();
            setResponse(fresh);
        } catch (e) {
            if (e.isConflict && e.serverSettings) {
                console.log("Conflict detected on Autonomy, retrying...");
                try {
                    const retryInner = e.serverSettings;
                    const retryPayload = {
                        ...retryInner,
                        learning: { ...(retryInner.learning || {}), auto_apply_safe: enabled },
                        version: e.serverVersion
                    };
                    await updateSettings(retryPayload);
                    const fresh = await getSettings();
                    setResponse(fresh);
                } catch (retryErr) {
                    alert("Error tras reintento: " + retryErr.message);
                    const fresh = await getSettings();
                    setResponse(fresh);
                }
            } else {
                alert("Error: " + e.message);
                const fresh = await getSettings();
                setResponse(fresh);
            }
        }
    };

    if (loading) return <div className="p-4 text-center">Cargando Labs...</div>;

    return (
        <div className="stack">
            <h3 style={{ marginTop: 0 }}>Aprendizaje y Autonomía</h3>
            <p className="text-muted text-sm" style={{ marginBottom: '1.5rem' }}>
                Funciones de aprendizaje automático y control de autonomía. El sistema registra resultados para mejorar sugerencias.
            </p>

            <div style={{ padding: '1rem', background: '#fff7ed', borderRadius: '8px', border: '1px solid #fed7aa', marginBottom: '1rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <div style={{ fontWeight: 600, color: '#c2410c' }}>Aplicar Correcciones (Autonomy)</div>
                        <div style={{ fontSize: '0.8rem', color: '#9a3412', marginTop: '2px' }}>
                            Permitir que la IA ajuste tus bolos automáticamente si la confianza es alta.
                        </div>
                    </div>
                    <label className="switch warning">
                        <input
                            type="checkbox"
                            checked={inner?.learning?.auto_apply_safe ?? false}
                            onChange={e => {
                                if (e.target.checked && !window.confirm("⚠️ ¿Seguro? Esto permitirá a la IA modificar dosis. Requiere supervisión.")) return;
                                handleUpdateAutonomy(e.target.checked);
                            }}
                        />
                        <span className="slider"></span>
                    </label>
                </div>
                {inner?.learning?.auto_apply_safe && (
                    <div className="fade-in" style={{ marginTop: '0.8rem', fontSize: '0.8rem', color: '#c2410c', background: '#ffedd5', padding: '0.5rem', borderRadius: '6px' }}>
                        <strong>⚠️ PRECAUCIÓN:</strong> Modo autónomo activo. Revisa siempre los registros.
                    </div>
                )}
            </div>

            <h4 style={{ margin: '1.5rem 0 0.5rem 0', fontSize: '0.9rem', color: '#475569' }}>Historial de Aprendizaje</h4>
            {logs.length === 0 && (
                <div style={{ padding: '1rem', textAlign: 'center', color: '#94a3b8', fontSize: '0.85rem', border: '1px dashed #cbd5e1', borderRadius: '6px' }}>
                    ⏳ Sin datos recientes. Usa el sistema para generar aprendizaje.
                </div>
            )}
            <div className="stack" style={{ gap: '0.5rem' }}>
                {logs.map(log => (
                    <div key={log.id} style={{
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                        padding: '0.6rem', background: '#f8fafc', borderRadius: '6px', border: '1px solid #e2e8f0', fontSize: '0.85rem'
                    }}>
                        <div>
                            <div style={{ fontWeight: 600, color: '#334155' }}>{log.meal_name || "Comida"}</div>
                            <div style={{ fontSize: '0.75rem', color: '#64748b' }}>{new Date(log.created_at).toLocaleString()}</div>
                            <div style={{ color: '#475569', marginTop: '2px' }}>{log.suggestion}</div>
                        </div>
                        <div style={{
                            fontWeight: 700,
                            color: (log.is_better || log.status === 'success') ? '#16a34a' : '#f59e0b',
                            fontSize: '0.8rem'
                        }}>
                            {(log.is_better || log.status === 'success') ? "OK" : "Revisar"}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}

function IngestLogsPanel() {
    const [logs, setLogs] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const [draft, setDraft] = useState(null);

    const load = async () => {
        setLoading(true);
        setError(null);
        try {
            const [logsData, draftData] = await Promise.all([
                fetchIngestLogs(),
                getNutritionDraft().catch(e => ({ active: false }))
            ]);
            setLogs(logsData);
            setDraft(draftData.active ? draftData.draft : null);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    };

    const handleDiscardDraft = async () => {
        if (!confirm("¿Descartar borrador actual?")) return;
        try {
            await discardNutritionDraft();
            await load();
        } catch (e) {
            alert(e.message);
        }
    };

    useEffect(() => {
        load();
    }, []);

    const copyToClipboard = (text) => {
        navigator.clipboard.writeText(text).then(() => {
            alert("Copiado al portapapeles");
        });
    };

    return (
        <div className="stack">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h3 style={{ margin: 0 }}>Registro de Ingesta (AutoExport)</h3>
                <Button variant="secondary" onClick={load} disabled={loading}>
                    {loading ? 'Refrescando...' : '🔄 Refrescar'}
                </Button>
            </div>
            <p className="text-muted text-sm">
                Muestra los últimos 50 intentos de entrada de datos externos (Shortcuts / AutoExport).
                Útil para depurar por qué no aparecen las comidas.
            </p>

            {draft && (
                <div className="fade-in" style={{
                    border: '2px solid #3b82f6',
                    borderRadius: '8px',
                    padding: '1rem',
                    background: '#eff6ff',
                    marginBottom: '1rem'
                }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <h4 style={{ margin: 0, color: '#1e3a8a' }}>Borrador Activo</h4>
                        <Button variant="danger" style={{ padding: '0.3rem 0.6rem', fontSize: '0.8rem' }} onClick={handleDiscardDraft}>
                            🗑️ Descartar
                        </Button>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.5rem', marginTop: '0.8rem', textAlign: 'center' }}>
                        <div style={{ background: '#fff', padding: '0.5rem', borderRadius: '6px' }}>
                            <div style={{ fontSize: '0.75rem', color: '#64748b' }}>Carbs</div>
                            <div style={{ fontWeight: 'bold', fontSize: '1.2rem', color: '#3b82f6' }}>{draft.carbs}</div>
                        </div>
                        <div style={{ background: '#fff', padding: '0.5rem', borderRadius: '6px' }}>
                            <div style={{ fontSize: '0.75rem', color: '#64748b' }}>Grasas</div>
                            <div style={{ fontWeight: 'bold', fontSize: '1.2rem', color: '#f59e0b' }}>{draft.fat}</div>
                        </div>
                        <div style={{ background: '#fff', padding: '0.5rem', borderRadius: '6px' }}>
                            <div style={{ fontSize: '0.75rem', color: '#64748b' }}>Prot</div>
                            <div style={{ fontWeight: 'bold', fontSize: '1.2rem', color: '#ef4444' }}>{draft.protein}</div>
                        </div>
                        <div style={{ background: '#fff', padding: '0.5rem', borderRadius: '6px' }}>
                            <div style={{ fontSize: '0.75rem', color: '#64748b' }}>Fibra</div>
                            <div style={{ fontWeight: 'bold', fontSize: '1.2rem', color: '#10b981' }}>{draft.fiber}</div>
                        </div>
                    </div>
                    <div style={{ fontSize: '0.75rem', color: '#60a5fa', marginTop: '0.5rem', textAlign: 'right' }}>
                        ID: {draft.id.substring(0, 8)}...
                    </div>
                </div>
            )
            }

            {
                error && (
                    <div style={{ padding: '1rem', background: '#fee2e2', color: '#b91c1c', borderRadius: '8px' }}>
                        Error: {error}
                    </div>
                )
            }

            {
                !loading && logs.length === 0 && (
                    <div style={{ padding: '2rem', textAlign: 'center', color: '#64748b' }}>
                        No hay registros disponibles.
                    </div>
                )
            }

            <div className="stack" style={{ gap: '1rem' }}>
                {logs.map((log, i) => (
                    <div key={i} style={{
                        border: '1px solid #e2e8f0',
                        borderRadius: '8px',
                        padding: '1rem',
                        background: log.status === 'success' ? '#f0fdf4' :
                            log.status === 'rejected' ? '#fee2e2' :
                                log.status === 'error' ? '#fef2f2' :
                                    log.status === 'ignored' ? '#f8fafc' : '#fff'
                    }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                            <div>
                                <span style={{
                                    fontWeight: 'bold',
                                    color: log.status === 'success' ? '#166534' :
                                        log.status === 'rejected' ? '#991b1b' :
                                            log.status === 'error' ? '#991b1b' :
                                                log.status === 'ignored' ? '#64748b' : '#334155'
                                }}>
                                    {log.status?.toUpperCase()}
                                </span>
                                <span style={{ marginLeft: '10px', color: '#64748b', fontSize: '0.9rem' }}>
                                    {new Date(log.timestamp).toLocaleString()}
                                </span>
                            </div>
                            <Button
                                variant="secondary"
                                style={{ padding: '0.2rem 0.6rem', fontSize: '0.8rem' }}
                                onClick={() => copyToClipboard(JSON.stringify(log, null, 2))}
                            >
                                📋 JSON
                            </Button>
                        </div>

                        <div style={{ background: '#1e293b', color: '#f8fafc', padding: '0.8rem', borderRadius: '6px', overflowX: 'auto', fontSize: '0.8rem' }}>
                            <div style={{ fontWeight: 'bold', color: '#94a3b8', marginBottom: '4px' }}>Resultado:</div>
                            <pre style={{ margin: 0 }}>{JSON.stringify(log.result, null, 2)}</pre>
                        </div>
                        {log.payload && (
                            <details style={{ marginTop: '0.5rem', fontSize: '0.85rem' }}>
                                <summary style={{ cursor: 'pointer', color: '#475569', fontWeight: 600 }}>Ver Payload Original</summary>
                                <div style={{ marginTop: '0.4rem', background: '#f1f5f9', padding: '0.5rem', borderRadius: '4px', border: '1px solid #e2e8f0' }}>
                                    <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: '0.75rem' }}>{JSON.stringify(log.payload, null, 2)}</pre>
                                </div>
                            </details>
                        )}
                    </div>
                ))}
            </div>
        </div>
    );
}

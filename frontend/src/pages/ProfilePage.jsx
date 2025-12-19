import React, { useState } from 'react';
import { Header } from '../components/layout/Header';
import { changePassword, updateProfile } from '../lib/api';
import { useStore } from '../hooks/useStore';
import { navigate } from '../modules/core/router';
import { Card, Button } from '../components/ui/Atoms';

export default function ProfilePage() {
    const user = useStore(s => s.user);
    const [tab, setTab] = useState('general'); // 'general' | 'security'

    return (
        <>
            <Header title="Mi Perfil" showBack={true} />
            <main className="page" style={{ padding: '1rem', maxWidth: '600px', margin: '0 auto' }}>

                <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem' }}>
                    <TabButton active={tab === 'general'} onClick={() => setTab('general')}>General</TabButton>
                    <TabButton active={tab === 'security'} onClick={() => setTab('security')}>Seguridad</TabButton>
                    <TabButton active={tab === 'sick'} onClick={() => setTab('sick')} danger={true}>Enfermedad</TabButton>
                </div>

                {tab === 'general' && <GeneralSection user={user} />}
                {tab === 'security' && <SecuritySection />}
                {tab === 'sick' && <SickModeSection />}

            </main>
        </>
    );
}

function TabButton({ active, onClick, children, danger }) {
    const bg = active
        ? (danger ? '#ef4444' : 'var(--primary)')
        : (danger ? '#fee2e2' : '#e2e8f0');

    const color = active
        ? 'white'
        : (danger ? '#ef4444' : '#64748b');

    return (
        <button
            onClick={onClick}
            style={{
                flex: 1, padding: '10px', borderRadius: '8px', border: 'none',
                background: bg,
                color: color,
                fontWeight: 600,
                fontSize: '0.85rem'
            }}
        >
            {children}
        </button>
    );
}

function SickModeSection() {
    // Logic for Sick Mode
    // Key: 'sick_mode_enabled' (true/false)
    const [enabled, setEnabled] = useState(() => {
        return localStorage.getItem('sick_mode_enabled') === 'true';
    });

    const toggle = () => {
        const newVal = !enabled;
        setEnabled(newVal);
        localStorage.setItem('sick_mode_enabled', newVal.toString());
        // Force refresh of layout maybe? Or utilize a global store?
        // Ideally we should use the store, but for v1 localStorage is fine.
        // Other components reading this need to know.
        // We will make BolusPage read from localStorage on mount/interaction.

        // Notify user
        if (newVal) alert("⚠️ MODO ENFERMEDAD ACTIVADO\n\n- Se aumentarán los ratios de insulina un 20%.\n- Se sugerirá medir cetonas si la glucosa es alta.\n- Revisa tu basal (considera un +20%).");
    };

    return (
        <Card style={{ border: enabled ? '2px solid #ef4444' : 'none' }}>
            <h3 className="text-lg font-bold mb-4" style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                🤒 Modo Enfermedad
                {enabled && <span style={{ fontSize: '0.8rem', background: '#ef4444', color: 'white', padding: '2px 8px', borderRadius: '10px' }}>ACTIVO</span>}
            </h3>

            <p style={{ marginBottom: '1.5rem', fontSize: '0.9rem', color: '#64748b', lineHeight: 1.5 }}>
                Activa este modo cuando tengas fiebre, infección o enfermedad. El estrés físico aumenta la resistencia a la insulina.
            </p>

            <div style={{ background: enabled ? '#fef2f2' : '#f8fafc', padding: '1.5rem', borderRadius: '12px', textAlign: 'center', marginBottom: '1.5rem', border: enabled ? '1px solid #fecaca' : '1px solid #e2e8f0' }}>
                <div style={{ fontSize: '3rem', marginBottom: '0.5rem' }}>{enabled ? '🔥' : '❄️'}</div>
                <div style={{ fontWeight: 800, fontSize: '1.2rem', color: enabled ? '#ef4444' : '#64748b', marginBottom: '1rem' }}>
                    {enabled ? 'ESTÁS EN MODO ENFERMEDAD' : 'Modo Normal'}
                </div>
                <Button
                    onClick={toggle}
                    style={{
                        background: enabled ? 'white' : '#ef4444',
                        color: enabled ? '#ef4444' : 'white',
                        border: enabled ? '2px solid #ef4444' : 'none',
                        width: '100%',
                        fontWeight: 700
                    }}
                >
                    {enabled ? 'Desactivar' : 'ACTIVAR MODO ENFERMEDAD'}
                </Button>
            </div>

            <div style={{ fontSize: '0.85rem' }}>
                <strong>Efectos automáticos:</strong>
                <ul style={{ paddingLeft: '1.2rem', color: '#475569', marginTop: '0.5rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    <li>📈 <strong>Bolos más agresivos:</strong> Ratios (ICR/ISF) aumentados un 20%.</li>
                    <li>🧪 <strong>Alerta de Cetonas:</strong> Recordatorio si Glucosa > 250 mg/dL.</li>
                    <li>💉 <strong>Basal:</strong> Se sugiere aumentar la dosis manual un 20-30%.</li>
                </ul>
            </div>
        </Card>
    );
}

function PasswordInput({ value, onChange, placeholder, required = false, minLength }) {
    const [show, setShow] = useState(false);
    return (
        <div style={{ position: 'relative' }}>
            <input
                className="w-full border rounded p-2"
                type={show ? "text" : "password"}
                placeholder={placeholder}
                value={value}
                onChange={onChange}
                minLength={minLength}
                required={required}
                style={{ paddingRight: '40px' }}
            />
            <button
                type="button"
                onClick={() => setShow(!show)}
                style={{
                    position: 'absolute', right: '5px', top: '50%', transform: 'translateY(-50%)',
                    background: 'none', border: 'none', cursor: 'pointer', padding: '5px', color: '#64748b', fontSize: '1.2rem'
                }}
                tabIndex="-1"
            >
                {show ? '👁️' : '🔒'}
            </button>
        </div>
    );
}

function GeneralSection({ user }) {
    const [username, setUsername] = useState(user?.username || '');
    const [password, setPassword] = useState(''); // Need pass to confirm
    const [msg, setMsg] = useState(null);
    const [loading, setLoading] = useState(false);

    const handleSave = async (e) => {
        e.preventDefault();
        setLoading(true);
        setMsg(null);
        try {
            await updateProfile(username, password);
            setMsg({ type: 'success', text: 'Nombre de usuario actualizado.' });
            setPassword(''); // clear password
            // Navigate back or refresh? Store auto-updates via api.ts
        } catch (err) {
            setMsg({ type: 'error', text: err.message });
        } finally {
            setLoading(false);
        }
    };

    return (
        <Card>
            <h3 className="text-lg font-bold mb-4">Información de Cuenta</h3>
            {msg && <div className={`alert ${msg.type === 'error' ? 'alert-danger' : 'alert-success'}`} style={{ padding: '10px', borderRadius: '8px', marginBottom: '1rem', background: msg.type === 'error' ? '#fee2e2' : '#dcfce7', color: msg.type === 'error' ? '#991b1b' : '#166534' }}>{msg.text}</div>}

            <form onSubmit={handleSave} className="space-y-4">
                <div>
                    <label className="block font-medium mb-1">Nombre de Usuario</label>
                    <input
                        className="w-full border rounded p-2"
                        type="text"
                        value={username}
                        onChange={e => setUsername(e.target.value)}
                        minLength={3}
                        required
                    />
                    <p className="text-xs text-gray-500 mt-1">
                        Cambiar esto actualizará tu historial y configuración automáticamente.
                    </p>
                </div>

                <div style={{ marginTop: '1rem', borderTop: '1px solid #eee', paddingTop: '1rem' }}>
                    <label className="block font-medium mb-1">Confirma tu contraseña actual</label>
                    <PasswordInput
                        placeholder="Contraseña actual"
                        value={password}
                        onChange={e => setPassword(e.target.value)}
                        required={true}
                    />
                </div>

                <Button type="submit" disabled={loading || !password} style={{ width: '100%', marginTop: '1rem' }}>
                    {loading ? 'Guardando...' : 'Guardar Cambios'}
                </Button>
            </form>
        </Card>
    );
}

function SecuritySection() {
    const [oldPass, setOldPass] = useState('');
    const [newPass, setNewPass] = useState('');
    const [msg, setMsg] = useState(null);
    const [loading, setLoading] = useState(false);

    const handleChangePass = async (e) => {
        e.preventDefault();
        setLoading(true);
        setMsg(null);
        try {
            await changePassword(oldPass, newPass);
            setMsg({ type: 'success', text: 'Contraseña actualizada correctamente.' });
            setOldPass('');
            setNewPass('');
        } catch (err) {
            setMsg({ type: 'error', text: err.message });
        } finally {
            setLoading(false);
        }
    };

    return (
        <Card>
            <h3 className="text-lg font-bold mb-4">Cambiar Contraseña</h3>
            {msg && <div className={`alert ${msg.type === 'error' ? 'alert-danger' : 'alert-success'}`} style={{ padding: '10px', borderRadius: '8px', marginBottom: '1rem', background: msg.type === 'error' ? '#fee2e2' : '#dcfce7', color: msg.type === 'error' ? '#991b1b' : '#166534' }}>{msg.text}</div>}

            <form onSubmit={handleChangePass} className="space-y-4">
                <div>
                    <label className="block font-medium mb-1">Contraseña Actual</label>
                    <PasswordInput
                        value={oldPass}
                        onChange={e => setOldPass(e.target.value)}
                        required={true}
                    />
                </div>
                <div>
                    <label className="block font-medium mb-1">Nueva Contraseña</label>
                    <PasswordInput
                        value={newPass}
                        onChange={e => setNewPass(e.target.value)}
                        minLength={8}
                        required={true}
                    />
                </div>

                <Button type="submit" disabled={loading} style={{ width: '100%', marginTop: '1rem' }}>
                    {loading ? 'Actualizando...' : 'Actualizar Contraseña'}
                </Button>
            </form>
        </Card>
    );
}

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
                </div>

                {tab === 'general' && <GeneralSection user={user} />}
                {tab === 'security' && <SecuritySection />}

            </main>
        </>
    );
}

function TabButton({ active, onClick, children }) {
    return (
        <button
            onClick={onClick}
            style={{
                flex: 1, padding: '10px', borderRadius: '8px', border: 'none',
                background: active ? 'var(--primary)' : '#e2e8f0',
                color: active ? 'white' : '#64748b',
                fontWeight: 600
            }}
        >
            {children}
        </button>
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
                    <input
                        className="w-full border rounded p-2"
                        type="password"
                        placeholder="Contraseña actual"
                        value={password}
                        onChange={e => setPassword(e.target.value)}
                        required
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
                    <input
                        className="w-full border rounded p-2"
                        type="password"
                        value={oldPass}
                        onChange={e => setOldPass(e.target.value)}
                        required
                    />
                </div>
                <div>
                    <label className="block font-medium mb-1">Nueva Contraseña</label>
                    <input
                        className="w-full border rounded p-2"
                        type="password"
                        value={newPass}
                        onChange={e => setNewPass(e.target.value)}
                        minLength={8}
                        required
                    />
                </div>

                <Button type="submit" disabled={loading} style={{ width: '100%', marginTop: '1rem' }}>
                    {loading ? 'Actualizando...' : 'Actualizar Contraseña'}
                </Button>
            </form>
        </Card>
    );
}

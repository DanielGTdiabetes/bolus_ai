import React, { useState } from 'react';
import { Header } from '../components/layout/Header';
import { Button, Input, Card } from '../components/ui/Atoms';
import { changePassword, saveSession } from '../lib/api';
import { navigate } from '../modules/core/navigation';
import { state } from '../modules/core/store';

export default function ChangePasswordPage() {
    const [oldPass, setOldPass] = useState('');
    const [newPass, setNewPass] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [success, setSuccess] = useState(false);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setLoading(true);
        setError(null);
        setSuccess(false);

        try {
            const result = await changePassword(oldPass, newPass);
            state.user = result.user || state.user;

            if (typeof saveSession === 'function') {
                saveSession(state.token, state.user);
            }

            setSuccess(true);
            setTimeout(() => navigate("#/"), 1000);
        } catch (err) {
            setError(err.message || "No se pudo actualizar");
        } finally {
            setLoading(false);
        }
    };

    return (
        <>
            <Header title="Seguridad" showBack={true} />
            <main className="page narrow" style={{ paddingTop: '2rem' }}>
                <Card className="auth-card">
                    <h2 style={{ fontSize: '1.3rem', marginBottom: '1rem' }}>Cambiar contraseña</h2>
                    <p className="hint" style={{ marginBottom: '1.5rem' }}>Introduce tu contraseña actual y una nueva (mínimo 8 caracteres).</p>

                    <form onSubmit={handleSubmit} className="stack">
                        <div>
                            <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 600 }}>Contraseña actual</label>
                            <Input
                                type="password"
                                autoComplete="current-password"
                                required
                                value={oldPass}
                                onChange={e => setOldPass(e.target.value)}
                                style={{ width: '100%' }}
                            />
                        </div>
                        <div>
                            <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 600 }}>Nueva contraseña</label>
                            <Input
                                type="password"
                                autoComplete="new-password"
                                required
                                minLength={8}
                                value={newPass}
                                onChange={e => setNewPass(e.target.value)}
                                style={{ width: '100%' }}
                            />
                        </div>

                        <Button type="submit" disabled={loading} style={{ width: '100%', marginTop: '1rem' }}>
                            {loading ? 'Actualizando...' : 'Actualizar'}
                        </Button>

                        {error && (
                            <div className="error" style={{ background: '#fee2e2', color: '#991b1b', padding: '0.8rem', borderRadius: '8px', marginTop: '1rem' }}>
                                {error}
                            </div>
                        )}

                        {success && (
                            <div className="success" style={{ background: '#dcfce7', color: '#166534', padding: '0.8rem', borderRadius: '8px', marginTop: '1rem' }}>
                                Contraseña actualizada.
                            </div>
                        )}
                    </form>
                </Card>
            </main>
        </>
    );
}

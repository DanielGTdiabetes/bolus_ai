import React, { useState } from 'react';
import { Header } from '../components/layout/Header';
import { Button, Input, Card } from '../components/ui/Atoms';
import { loginRequest, saveSession } from '../lib/api';
import { navigate } from '../modules/core/navigation';
import { state } from '../modules/core/store';

export default function LoginPage() {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setLoading(true);
        setError(null);

        try {
            const data = await loginRequest(username, password);
            state.token = data.access_token;
            state.user = data.user;

            if (typeof saveSession === 'function') {
                saveSession(state.token, state.user);
            }

            if (data.user.needs_password_change) {
                navigate("#/change-password");
            } else {
                navigate("#/");
            }
        } catch (err) {
            setError(err.message || "No se pudo iniciar sesión");
        } finally {
            setLoading(false);
        }
    };

    return (
        <main className="page narrow" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', minHeight: '100vh', padding: '1rem' }}>
            <header className="topbar" style={{ justifyContent: 'center', marginBottom: '2rem', background: 'transparent' }}>
                <div style={{ fontSize: '1.5rem', fontWeight: '900', background: 'linear-gradient(135deg, #2563eb, #3b82f6)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
                    Bolus AI
                </div>
            </header>

            <Card className="auth-card" style={{ padding: '2rem' }}>
                <h1 style={{ fontSize: '1.5rem', marginBottom: '1.5rem' }}>Inicia sesión</h1>

                <form onSubmit={handleSubmit} className="stack">
                    <div>
                        <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 600 }}>Usuario</label>
                        <Input
                            type="text"
                            autoComplete="username"
                            required
                            value={username}
                            onChange={e => setUsername(e.target.value)}
                            style={{ width: '100%' }}
                        />
                    </div>
                    <div>
                        <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 600 }}>Contraseña</label>
                        <Input
                            type="password"
                            autoComplete="current-password"
                            required
                            value={password}
                            onChange={e => setPassword(e.target.value)}
                            style={{ width: '100%' }}
                        />
                    </div>

                    <Button type="submit" disabled={loading} style={{ width: '100%', marginTop: '1rem', padding: '0.8rem' }}>
                        {loading ? 'Entrando...' : 'Entrar'}
                    </Button>

                    <p className="hint" style={{ textAlign: 'center', marginTop: '1rem' }}>Se mantendrá la sesión.</p>

                    {error && (
                        <div className="error" style={{ background: '#fee2e2', color: '#991b1b', padding: '0.8rem', borderRadius: '8px', marginTop: '1rem', textAlign: 'center' }}>
                            {error}
                        </div>
                    )}
                </form>
            </Card>
        </main>
    );
}

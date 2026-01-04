import React from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { navigate } from '../modules/core/router';
import { Card } from '../components/ui/Atoms';

function MenuSection({ title, items }) {
    return (
        <Card style={{ marginBottom: '1rem', padding: '0' }}>
            {title && <div style={{ padding: '1rem', borderBottom: '1px solid #f1f5f9', fontWeight: 600, color: '#64748b', fontSize: '0.9rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{title}</div>}
            <div style={{ display: 'flex', flexDirection: 'column' }}>
                {items.map((item, idx) => (
                    <button
                        key={idx}
                        onClick={() => navigate(item.hash)}
                        style={{
                            display: 'flex', alignItems: 'center', gap: '1rem',
                            padding: '1rem', background: 'transparent', border: 'none',
                            borderBottom: idx < items.length - 1 ? '1px solid #f8fafc' : 'none',
                            cursor: 'pointer', textAlign: 'left'
                        }}
                    >
                        <div style={{
                            width: '36px', height: '36px', borderRadius: '8px',
                            background: item.bg || '#f1f5f9', color: item.color || '#475569',
                            display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.2rem'
                        }}>
                            {item.icon}
                        </div>
                        <div style={{ flex: 1 }}>
                            <div style={{ fontSize: '1rem', fontWeight: 600, color: '#334155' }}>{item.label}</div>
                            {item.sub && <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>{item.sub}</div>}
                        </div>
                        <div style={{ color: '#cbd5e1' }}>›</div>
                    </button>
                ))}
            </div>
        </Card>
    );
}

export default function MenuPage() {
    return (
        <>
            <Header title="Menú" showBack={false} />
            <main className="page" style={{ paddingBottom: '90px' }}>
                <MenuSection title="Mi Salud" items={[
                    { icon: '⏱️', label: 'Historial', sub: 'Registro de bolos y comidas', hash: '#/history', color: '#3b82f6', bg: '#eff6ff' },
                    { icon: '📊', label: 'Patrones', sub: 'Análisis de tendencias', hash: '#/patterns', color: '#8b5cf6', bg: '#f5f3ff' },
                    { icon: '💡', label: 'Sugerencias', sub: 'Recomendaciones IA', hash: '#/suggestions', color: '#f59e0b', bg: '#fffbeb' },
                    { icon: '📚', label: 'Mis Platos', sub: 'Librería personal', hash: '#/favorites', color: '#ec4899', bg: '#fdf2f8' },
                    { icon: '📍', label: 'Mapa Corporal', sub: 'Gestión de rotación', hash: '#/bodymap', color: '#f43f5e', bg: '#fff1f2' }
                ]} />

                <MenuSection title="Cuenta y Sistema" items={[
                    { icon: '📦', label: 'Suministros', sub: 'Stock de agujas', hash: '#/supplies', color: '#0ea5e9', bg: '#e0f2fe' },
                    { icon: '🚨', label: 'Calculadora Manual de Emergencia', sub: 'Calc. manual sin conexión', hash: '#/manual', color: '#ef4444', bg: '#fef2f2' },
                    { icon: '👤', label: 'Mi Perfil', sub: 'Datos personales e insulina', hash: '#/profile', color: '#10b981', bg: '#ecfdf5' },
                    { icon: '⚙️', label: 'Ajustes', sub: 'Configuración general', hash: '#/settings', color: '#64748b', bg: '#f1f5f9' }
                ]} />
            </main>
            <BottomNav activeTab="menu" />
        </>
    );
}

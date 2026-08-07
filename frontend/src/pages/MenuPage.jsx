import React, { useEffect, useState } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { navigate } from '../modules/core/navigation';
import { Card } from '../components/ui/Atoms';
import { logout } from '../lib/api';

const sections = [
    {
        title: 'Seguimiento',
        items: [
            { icon: '♥', label: 'Mi compañero', sub: 'Estado, avisos y preferencias', hash: '#/notifications', tone: 'indigo' },
            { icon: '↗', label: 'Predicción', sub: 'Tendencia y evolución estimada', hash: '#/forecast', tone: 'blue' },
            { icon: '◒', label: 'Asistente basal', sub: 'Registro y revisión de la basal', hash: '#/basal', tone: 'teal' },
            { icon: '✓', label: 'Comprobar ISF', sub: 'Analiza correcciones limpias', hash: '#/settings', tone: 'violet' },
        ],
    },
    {
        title: 'Comida y cálculo',
        items: [
            { icon: '◎', label: 'Escanear comida', sub: 'Foto, pluma o báscula opcional', hash: '#/scan', tone: 'amber' },
            { icon: '+', label: 'Calcular bolo', sub: 'Calculadora segura conectada', hash: '#/bolus', tone: 'blue' },
            { icon: '≡', label: 'Base de alimentos', sub: 'Alimentos, macros y favoritos', hash: '#/food-db', tone: 'orange' },
            { icon: '★', label: 'Mis platos', sub: 'Biblioteca personal', hash: '#/favorites', tone: 'pink' },
        ],
    },
    {
        title: 'Historial y aprendizaje',
        items: [
            { icon: '↺', label: 'Historial', sub: 'Bolos, comidas y tratamientos', hash: '#/history', tone: 'slate' },
            { icon: '◇', label: 'Aprendizaje', sub: 'Patrones y absorción', hash: '#/learning', tone: 'violet' },
            { icon: '✦', label: 'Sugerencias', sub: 'Recomendaciones para revisar', hash: '#/suggestions', tone: 'amber' },
            { icon: '⌖', label: 'Mapa corporal', sub: 'Rotación de zonas de inyección', hash: '#/bodymap', tone: 'rose' },
        ],
    },
    {
        title: 'Cuenta y sistema',
        items: [
            { icon: '○', label: 'Mi perfil', sub: 'Datos personales y parámetros', hash: '#/profile', tone: 'teal' },
            { icon: '□', label: 'Suministros', sub: 'Agujas y sensores', hash: '#/supplies', tone: 'cyan' },
            { icon: '●', label: 'Estado del sistema', sub: 'NAS, datos y modelos', hash: '#/status', tone: 'green' },
            { icon: '⚙', label: 'Ajustes de Bolus AI', sub: 'Perfil, visión y Nightscout', hash: '#/settings', tone: 'slate' },
            { icon: '!', label: 'Calculadora de emergencia', sub: 'Cálculo manual de contingencia', hash: '#/manual', tone: 'red' },
        ],
    },
];

function MenuSection({ title, items }) {
    return (
        <section className="menu-section">
            <h2>{title}</h2>
            <Card className="menu-card">
                {items.map(item => (
                    <button key={item.hash + item.label} className="menu-row" onClick={() => navigate(item.hash)}>
                        <span className={`menu-icon tone-${item.tone}`}>{item.icon}</span>
                        <span className="menu-copy">
                            <strong>{item.label}</strong>
                            <small>{item.sub}</small>
                        </span>
                        <span className="menu-chevron">›</span>
                    </button>
                ))}
            </Card>
        </section>
    );
}

function AndroidTools() {
    const [available, setAvailable] = useState(false);

    useEffect(() => {
        setAvailable(Boolean(window.AndroidCompanionInterface));
    }, []);

    if (!available) return null;

    const openNative = method => {
        const bridge = window.AndroidCompanionInterface;
        if (bridge && typeof bridge[method] === 'function') bridge[method]();
    };

    return (
        <section className="menu-section android-tools">
            <div className="android-tools-heading">
                <div>
                    <span className="eyebrow">En este móvil</span>
                    <h2>Integraciones Android</h2>
                </div>
                <span className="connected-pill">Conectado</span>
            </div>
            <Card className="menu-card">
                <button className="menu-row" onClick={() => openNative('openMobileHome')}>
                    <span className="menu-icon tone-teal">⇄</span>
                    <span className="menu-copy"><strong>Centro móvil</strong><small>MyFitnessPal, Dexcom y cola de envío</small></span>
                    <span className="menu-chevron">›</span>
                </button>
                <button className="menu-row" onClick={() => openNative('openDiagnostics')}>
                    <span className="menu-icon tone-green">●</span>
                    <span className="menu-copy"><strong>Estado de sincronización</strong><small>Comprobar lecturas y reintentos</small></span>
                    <span className="menu-chevron">›</span>
                </button>
                <button className="menu-row" onClick={() => openNative('openNativeScale')}>
                    <span className="menu-icon tone-blue">≈</span>
                    <span className="menu-copy"><strong>Báscula Bluetooth</strong><small>Pesaje nativo cuando esté disponible</small></span>
                    <span className="menu-chevron">›</span>
                </button>
                <button className="menu-row" onClick={() => openNative('openMobileSettings')}>
                    <span className="menu-icon tone-slate">⚙</span>
                    <span className="menu-copy"><strong>Ajustes del móvil</strong><small>Servidores, permisos e integraciones</small></span>
                    <span className="menu-chevron">›</span>
                </button>
            </Card>
        </section>
    );
}

export default function MenuPage() {
    return (
        <>
            <Header title="Más" showBack={false} />
            <main className="page menu-page">
                <div className="menu-intro">
                    <span className="eyebrow">Bolus AI Companion</span>
                    <h1>Todo en un solo sitio</h1>
                    <p>Las funciones diarias están arriba; configuración y herramientas avanzadas quedan aquí.</p>
                </div>

                <AndroidTools />
                {sections.map(section => <MenuSection key={section.title} {...section} />)}

                <button className="logout-row" onClick={() => logout()}>Cerrar sesión</button>
            </main>
            <BottomNav activeTab="menu" />
        </>
    );
}

import React, { useState, useEffect } from 'react';
import { Card, Button } from '../ui/Atoms';
import { connectScale, disconnectScale, tare, setOnData } from '../../lib/api';
import { state } from '../../modules/core/store';
import { navigate } from '../../modules/core/router';

export function ScaleSection({ onWeightUsed, onDataReceived }) {
    const [scale, setScale] = useState(state.scale || { connected: false, grams: 0, stable: true });

    useEffect(() => {
        const handler = (data) => {
            // Update global
            if (typeof data.grams === 'number') state.scale.grams = data.grams;
            if (typeof data.stable === 'boolean') state.scale.stable = data.stable;
            if (typeof data.connected === 'boolean') state.scale.connected = data.connected;
            if (typeof data.battery === 'number') state.scale.battery = data.battery;

            // Update local
            setScale({ ...state.scale });

            // Notify parent if needed
            if (onDataReceived) onDataReceived(data);
        };

        // We register the handler globally
        setOnData(handler);
        window.scaleHandler = handler;

        return () => { setOnData(null); };
    }, [onDataReceived]);

    const handleConnect = async () => {
        if (scale.connected) {
            await disconnectScale();
            setScale(prev => ({ ...prev, connected: false }));
            state.scale.connected = false;
        } else {
            try {
                await connectScale();
                state.scale.connected = true;
                setScale(prev => ({ ...prev, connected: true }));
                if (window.scaleHandler) setOnData(window.scaleHandler);
            } catch (e) {
                alert("Error conectando báscula: " + e.message);
            }
        }
    };

    const handleTare = async () => {
        await tare();
    };

    const handleUseWeight = () => {
        if (onWeightUsed) {
            onWeightUsed(scale.grams);
        } else {
            state.tempCarbs = scale.grams;
            navigate('#/bolus');
        }
    };

    return (
        <Card className="scale-card" style={{ marginTop: '1.5rem' }}>
            <h3 style={{ margin: '0 0 1rem 0' }}>⚖️ Báscula Bluetooth</h3>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <div className={`status-badge ${scale.connected ? 'success' : ''}`} style={{
                        padding: '0.25rem 0.75rem', borderRadius: '99px', fontSize: '0.75rem', fontWeight: 600,
                        background: scale.connected ? '#dcfce7' : '#f1f5f9', color: scale.connected ? '#166534' : '#64748b'
                    }}>
                        {scale.connected ? 'Conectado' : 'Desconectado'}
                    </div>
                    {scale.connected && scale.battery !== undefined && (
                        <div style={{ fontSize: '0.8rem', color: '#64748b', fontWeight: 600 }}>
                            🔋 {scale.battery}%
                        </div>
                    )}
                </div>
                <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: '2rem', fontWeight: 800, color: 'var(--primary)' }}>
                        {scale.grams !== null ? scale.grams : '--'} <span style={{ fontSize: '1rem' }}>g</span>
                    </div>
                </div>
            </div>

            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '1rem' }}>
                <Button variant="secondary" onClick={handleConnect} style={{ flex: 1 }}>
                    {scale.connected ? 'Desconectar' : 'Conectar'}
                </Button>
                <Button variant="ghost" onClick={handleTare} disabled={!scale.connected}>Tarar</Button>
                <Button onClick={handleUseWeight} disabled={!scale.connected || !scale.grams}>Usar Peso</Button>
            </div>
        </Card>
    );
}

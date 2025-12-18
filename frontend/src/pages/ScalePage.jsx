import React from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { ScaleSection } from '../components/scale/ScaleSection';

export default function ScalePage() {
    return (
        <>
            <Header title="Báscula" showBack={true} />
            <main className="page" style={{ paddingBottom: '90px' }}>
                <div className="stack" style={{ gap: '1rem' }}>
                    <p style={{ color: '#475569', fontSize: '0.9rem' }}>
                        Usa esta pantalla para pesar alimentos directamente. Puedes tarar el recipiente y usar el peso para calcular tu bolo.
                    </p>
                    <ScaleSection />
                </div>
            </main>
            <BottomNav activeTab="home" />
        </>
    );
}

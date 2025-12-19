import React, { useState, useEffect } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { Card, Button } from '../components/ui/Atoms';
import { getSupplies, updateSupply } from '../lib/api';

function StockItem({ title, storageKey, currentStock, onUpdate, boxSize = 100, warnThreshold = 20, dangerThreshold = 5 }) {
    const [editMode, setEditMode] = useState(false);
    const [manualVal, setManualVal] = useState('');

    const changeStock = (delta) => {
        const newVal = currentStock + delta;
        onUpdate(storageKey, newVal);
        if (delta > 5) alert(`✅ Añadidos ${delta} ${title}.`);
    };

    const saveManual = () => {
        const val = parseInt(manualVal);
        if (!isNaN(val)) {
            onUpdate(storageKey, val);
            setEditMode(false);
        }
    };

    let statusColor = "#10b981"; // Green
    let statusText = "🟢 Stock Saludable";
    if (currentStock < warnThreshold) { statusColor = "#f59e0b"; statusText = "🟠 Stock Medio"; }
    if (currentStock < dangerThreshold) { statusColor = "#ef4444"; statusText = "🔴 Stock Bajo"; }

    return (
        <Card className="stack" style={{ marginBottom: '1rem' }}>
            <div style={{ textAlign: 'center', padding: '1rem 0' }}>
                <div style={{ fontSize: '1rem', color: '#64748b', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    {title}
                </div>
                <div style={{ fontSize: '3.5rem', fontWeight: 800, color: statusColor, lineHeight: 1, margin: '0.5rem 0' }}>
                    {currentStock}
                </div>
                <div style={{ display: 'inline-block', padding: '4px 12px', borderRadius: '20px', background: `${statusColor}15`, color: statusColor, fontSize: '0.8rem', fontWeight: 700 }}>
                    {statusText}
                </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: boxSize > 1 ? '1fr 1fr' : '1fr', gap: '1rem', marginTop: '0.5rem' }}>
                {boxSize > 1 && (
                    <Button onClick={() => changeStock(boxSize)} style={{ background: '#f8fafc', color: '#334155', border: '1px solid #cbd5e1' }}>
                        📦 +{boxSize}
                    </Button>
                )}
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <Button onClick={() => changeStock(-1)} variant="ghost" style={{ flex: 1, border: '1px solid #e2e8f0' }}>-1</Button>
                    <Button onClick={() => changeStock(1)} variant="ghost" style={{ flex: 1, border: '1px solid #e2e8f0' }}>+1</Button>
                </div>
            </div>

            <div style={{ marginTop: '1.5rem', borderTop: '1px solid #f1f5f9', paddingTop: '1rem' }}>
                {editMode ? (
                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                        <input
                            type="number"
                            value={manualVal}
                            placeholder={currentStock}
                            onChange={e => setManualVal(e.target.value)}
                            style={{ flex: 1, padding: '0.8rem', borderRadius: '8px', border: '1px solid #cbd5e1' }}
                        />
                        <Button onClick={saveManual}>OK</Button>
                        <Button variant="ghost" onClick={() => setEditMode(false)}>Cancelar</Button>
                    </div>
                ) : (
                    <button
                        onClick={() => { setManualVal(currentStock); setEditMode(true); }}
                        style={{ width: '100%', padding: '0.5rem', background: 'transparent', border: 'none', color: '#94a3b8', textDecoration: 'underline', cursor: 'pointer', fontSize: '0.85rem' }}
                    >
                        ✏️ Corregir {title}
                    </button>
                )}
            </div>
        </Card>
    );
}

export default function SuppliesPage() {
    const [supplies, setSupplies] = useState({});
    const [loading, setLoading] = useState(true);

    const load = async () => {
        try {
            const data = await getSupplies();
            // Convert list [{key, quantity}] to dict {key: quantity}
            const map = {};
            data.forEach(item => map[item.key] = item.quantity);
            setSupplies(map);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { load(); }, []);

    const handleUpdate = async (key, val) => {
        // Optimistic update
        setSupplies(prev => ({ ...prev, [key]: val }));
        try {
            await updateSupply(key, val);
        } catch (e) {
            console.error(e);
            alert("Error guardando stock en la nube.");
            load(); // Revert
        }
    };

    if (loading) return <div className="page p-4">Cargando stock...</div>;

    return (
        <>
            <Header title="Suministros" showBack={true} />
            <main className="page" style={{ paddingBottom: '90px' }}>
                <StockItem
                    title="Agujas"
                    storageKey="supplies_needles"
                    currentStock={supplies["supplies_needles"] || 0}
                    onUpdate={handleUpdate}
                    boxSize={100}
                    warnThreshold={50}
                    dangerThreshold={20}
                />

                <StockItem
                    title="Sensores"
                    storageKey="supplies_sensors"
                    currentStock={supplies["supplies_sensors"] || 0}
                    onUpdate={handleUpdate}
                    boxSize={1}
                    warnThreshold={4}
                    dangerThreshold={2}
                />
            </main>
            <BottomNav activeTab="menu" />
        </>
    );
}

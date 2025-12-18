import React, { useState, useMemo } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { Card } from '../components/ui/Atoms';
import foodData from '../lib/foodData.json';

export default function FoodDatabasePage() {
    const [searchTerm, setSearchTerm] = useState('');
    const [selectedCategory, setSelectedCategory] = useState('Todos');

    const foods = foodData.foods || [];
    const categories = ['Todos', ...new Set(foods.map(f => f.category))];

    const filteredFoods = useMemo(() => {
        return foods.filter(food => {
            const matchesSearch = food.name.toLowerCase().includes(searchTerm.toLowerCase());
            const matchesCategory = selectedCategory === 'Todos' || food.category === selectedCategory;
            return matchesSearch && matchesCategory;
        });
    }, [foods, searchTerm, selectedCategory]);

    const getGIRating = (gi) => {
        if (!gi || gi === 0) return { label: 'Sin Datos', color: '#94a3b8', bg: '#f1f5f9' };
        if (gi >= 70) return { label: 'Alto', color: '#ef4444', bg: '#fef2f2' };
        if (gi >= 55) return { label: 'Medio', color: '#f59e0b', bg: '#fffbeb' };
        return { label: 'Bajo', color: '#10b981', bg: '#ecfdf5' };
    };

    return (
        <>
            <Header title="Base de Alimentos" showBack={true} />
            <main className="page" style={{ paddingBottom: '90px' }}>
                <section style={{ marginBottom: '1.5rem' }}>
                    <div style={{ position: 'relative', marginBottom: '1rem' }}>
                        <input
                            type="text"
                            placeholder="Buscar alimento (arroz, pan, leche...)"
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                            style={{
                                width: '100%',
                                padding: '1rem 1rem 1rem 3.2rem',
                                borderRadius: '18px',
                                border: '1px solid #e2e8f0',
                                fontSize: '1rem',
                                boxShadow: '0 4px 12px rgba(0, 0, 0, 0.05)',
                                outline: 'none',
                                transition: 'all 0.2s'
                            }}
                        />
                        <span style={{ position: 'absolute', left: '1.2rem', top: '50%', transform: 'translateY(-50%)', fontSize: '1.3rem' }}>🔍</span>
                        {searchTerm && (
                            <button
                                onClick={() => setSearchTerm('')}
                                style={{ position: 'absolute', right: '1rem', top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer', fontSize: '1.2rem' }}
                            >
                                ✕
                            </button>
                        )}
                    </div>

                    <div style={{ display: 'flex', gap: '0.6rem', overflowX: 'auto', paddingBottom: '0.5rem', scrollbarWidth: 'none', WebkitOverflowScrolling: 'touch' }}>
                        {categories.map(cat => (
                            <button
                                key={cat}
                                onClick={() => setSelectedCategory(cat)}
                                style={{
                                    padding: '0.7rem 1.4rem',
                                    borderRadius: '24px',
                                    border: 'none',
                                    background: selectedCategory === cat ? '#3b82f6' : '#fff',
                                    color: selectedCategory === cat ? '#fff' : '#475569',
                                    fontWeight: 700,
                                    fontSize: '0.8rem',
                                    whiteSpace: 'nowrap',
                                    boxShadow: selectedCategory === cat ? '0 4px 12px rgba(59, 130, 246, 0.3)' : '0 2px 4px rgba(0,0,0,0.05)',
                                    cursor: 'pointer',
                                    transition: 'all 0.2s',
                                    border: selectedCategory === cat ? 'none' : '1px solid #f1f5f9'
                                }}
                            >
                                {cat}
                            </button>
                        ))}
                    </div>
                </section>

                <section>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.2rem' }}>
                        <h3 style={{ margin: 0, fontSize: '1.1rem', color: '#1e293b', fontWeight: 800 }}>
                            {filteredFoods.length} {filteredFoods.length === 1 ? 'Alimento' : 'Alimentos'}
                        </h3>
                        <span style={{ fontSize: '0.75rem', color: '#94a3b8', fontWeight: 600 }}>1 ración = 10g HC</span>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                        {filteredFoods.length > 0 ? (
                            filteredFoods.map((food, idx) => {
                                const rating = getGIRating(food.ig);
                                return (
                                    <div key={idx} style={{
                                        background: '#fff',
                                        padding: '1.2rem',
                                        borderRadius: '20px',
                                        display: 'flex',
                                        flexDirection: 'column',
                                        gap: '0.8rem',
                                        boxShadow: '0 4px 6px -1px rgba(0,0,0,0.02), 0 2px 4px -1px rgba(0,0,0,0.06)',
                                        border: '1px solid #f8fafc',
                                        position: 'relative',
                                        overflow: 'hidden'
                                    }}>
                                        <div style={{ position: 'absolute', top: 0, left: 0, bottom: 0, width: '4px', backgroundColor: rating.color }}></div>

                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                            <div style={{ flex: 1 }}>
                                                <div style={{ fontWeight: 800, color: '#1e293b', fontSize: '1.05rem', marginBottom: '2px' }}>{food.name}</div>
                                                <div style={{ fontSize: '0.75rem', color: '#64748b', display: 'flex', alignItems: 'center', gap: '4px', fontWeight: 600 }}>
                                                    <span style={{ padding: '2px 6px', background: '#f1f5f9', borderRadius: '4px' }}>{food.category}</span>
                                                </div>
                                            </div>
                                            <div style={{ textAlign: 'right' }}>
                                                <div style={{
                                                    fontSize: '0.6rem',
                                                    fontWeight: 900,
                                                    textTransform: 'uppercase',
                                                    padding: '3px 8px',
                                                    borderRadius: '6px',
                                                    backgroundColor: rating.bg,
                                                    color: rating.color,
                                                    letterSpacing: '0.05em'
                                                }}>
                                                    IG {rating.label}
                                                </div>
                                            </div>
                                        </div>

                                        <div style={{ display: 'flex', gap: '1.5rem', marginTop: '0.2rem', padding: '0.8rem', background: '#f8fafc', borderRadius: '12px' }}>
                                            <div style={{ flex: 1 }}>
                                                <div style={{ fontSize: '0.65rem', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 800, marginBottom: '4px' }}>HC / 100g</div>
                                                <div style={{ fontSize: '1.1rem', fontWeight: 800, color: '#334155' }}>
                                                    {food.ch_per_100g} <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#64748b' }}>g</span>
                                                </div>
                                            </div>
                                            <div style={{ flex: 2, borderLeft: '1px solid #e2e8f0', paddingLeft: '1.5rem' }}>
                                                <div style={{ fontSize: '0.65rem', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 800, marginBottom: '4px' }}>Medida Habitual</div>
                                                <div style={{ fontSize: '0.9rem', fontWeight: 700, color: '#475569', lineHeight: '1.2' }}>
                                                    {food.measure || 'Sin especificar'}
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                );
                            })
                        ) : (
                            <div style={{ textAlign: 'center', padding: '4rem 2rem' }}>
                                <div style={{ fontSize: '4rem', marginBottom: '1.5rem', filter: 'grayscale(1)' }}>🥘</div>
                                <h4 style={{ color: '#475569', marginBottom: '0.5rem' }}>¿No encuentras lo que buscas?</h4>
                                <p style={{ color: '#94a3b8', fontSize: '0.9rem' }}>Intenta con términos más generales o cambia la categoría.</p>
                                <Button
                                    label="Ver todos los alimentos"
                                    onClick={() => { setSearchTerm(''); setSelectedCategory('Todos'); }}
                                    style={{ marginTop: '1.5rem' }}
                                />
                            </div>
                        )}
                    </div>
                </section>

                <div style={{
                    marginTop: '3rem',
                    padding: '1.5rem',
                    background: '#f1f5f9',
                    borderRadius: '20px',
                    border: '1px solid #e2e8f0',
                    textAlign: 'center'
                }}>
                    <div style={{ fontSize: '1.5rem', marginBottom: '0.5rem' }}>ℹ️</div>
                    <p style={{ fontSize: '0.8rem', color: '#64748b', margin: 0, lineHeight: '1.5', fontWeight: 500 }}>
                        Fuente: <strong>{foodData.source}</strong>.<br />
                        Los valores de Hidratos de Carbono (HC) son aproximados por cada 100g de producto.
                        Consulta siempre el etiquetado nutricional específico de tu marca.
                    </p>
                </div>
            </main>
            <BottomNav activeTab="" />
        </>
    );
}


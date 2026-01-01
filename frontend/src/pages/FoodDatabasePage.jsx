import React, { useState, useMemo, useEffect } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { Button } from '../components/ui/Atoms';
import foodData from '../lib/foodData.json';
import { state } from '../modules/core/store';
import { navigate } from '../modules/core/router';
import { getFavorites, saveFavorite, deleteFavorite } from '../lib/api';

export default function FoodDatabasePage() {
    const [searchTerm, setSearchTerm] = useState('');
    const [selectedCategory, setSelectedCategory] = useState('Todos');
    const [portions, setPortions] = useState({}); // { [foodName]: grams }

    // favorites now stores a Set of names for fast lookup, synchronized with backend
    const [favorites, setFavorites] = useState([]);
    const [favMap, setFavMap] = useState({}); // { 'Pizza': 'uuid-123' }

    const foods = foodData.foods || [];
    const categories = ['Todos', 'Favoritos', ...new Set(foods.map(f => f.category))];

    const categoryIcons = {
        'Lácteos': '🥛',
        'Cereales y Tubérculos': '🌾',
        'Frutas': '🍎',
        'Verduras y Hortalizas': '🥦',
        'Grasas y Frutos Secos': '🥜',
        'Bebidas': '🍹',
        'Otros / Platos Preparados': '🍕',
        'Carnes, Pescados y Huevos': '🍖',
        'Proteínas': '🍗',
        'Favoritos': '⭐',
        'Comida Rápida': '🍔',
        'Todos': '📂'
    };

    const [cart, setCart] = useState([]);
    const [isCartOpen, setIsCartOpen] = useState(false);

    useEffect(() => {
        loadBackendFavorites();
    }, []);

    const loadBackendFavorites = async () => {
        try {
            const data = await getFavorites();
            const names = data.map(f => f.name);
            const map = {};
            data.forEach(f => map[f.name] = f.id);

            setFavorites(names);
            setFavMap(map);
        } catch (e) {
            console.warn("Failed to load backend favorites", e);
        }
    };

    const toggleFavorite = async (food) => {
        const isFav = favorites.includes(food.name);

        // Optimistic UI Update
        if (isFav) {
            setFavorites(prev => prev.filter(n => n !== food.name));
            // Remove from backend
            const id = favMap[food.name];
            if (id) {
                try {
                    await deleteFavorite(id);
                    const newMap = { ...favMap };
                    delete newMap[food.name];
                    setFavMap(newMap);
                } catch (e) {
                    alert("Error eliminando favorito: " + e.message);
                    loadBackendFavorites(); // Revert
                }
            }
        } else {
            setFavorites(prev => [...prev, food.name]);
            // Add to backend
            try {
                // Heuristic: Pre-fill macros based on 100g or 1 serving? 
                // Database stores per 100g. We'll save the "Base" info.
                // Or maybe we save it as a "Reference".
                // Let's save 100g as default reference.
                const newFav = await saveFavorite({
                    name: food.name,
                    carbs: food.ch_per_100g,
                    fat: 0, // DB doesn't have fat/prot yet unfortunately, defaulting 0
                    protein: 0,
                    notes: `Base de Datos (${food.category})`
                });
                setFavMap(prev => ({ ...prev, [food.name]: newFav.id }));
            } catch (e) {
                alert("Error guardando favorito: " + e.message);
                loadBackendFavorites(); // Revert
            }
        }
    };

    const getGIRating = (gi) => {
        if (!gi || gi === 0) return { label: 'Sin Datos', color: '#94a3b8', bg: '#f1f5f9' };
        if (gi >= 70) return { label: 'Alto', color: '#ef4444', bg: '#fef2f2' };
        if (gi >= 55) return { label: 'Medio', color: '#f59e0b', bg: '#fffbeb' };
        return { label: 'Bajo', color: '#10b981', bg: '#ecfdf5' };
    };

    const handleAddToCart = (food, grams) => {
        if (!grams || grams <= 0 || isNaN(parseFloat(grams))) {
            alert("Introduce una cantidad válida en gramos primero.");
            return;
        }
        const calculatedCarbs = (food.ch_per_100g * parseFloat(grams)) / 100;
        const newItem = {
            name: food.name,
            amount: parseFloat(grams),
            carbs: Math.round(calculatedCarbs * 10) / 10,
            id: Date.now() // Simple ID
        };
        setCart(prev => [...prev, newItem]);

        // Visual feedback could be added here (e.g. toast), but for now we rely on the bar appearing
        setPortions(prev => ({ ...prev, [food.name]: '' })); // Clear input
    };

    const removeFromCart = (itemId) => {
        setCart(prev => prev.filter(item => item.id !== itemId));
    };

    const handleCheckout = () => {
        if (cart.length === 0) return;

        const totalCarbs = cart.reduce((sum, item) => sum + item.carbs, 0);
        state.tempCarbs = Math.round(totalCarbs * 10) / 10;
        state.tempItems = cart;

        navigate('#/bolus');
    };

    const filteredFoods = useMemo(() => {
        return foods.filter(food => {
            const matchesSearch = food.name.toLowerCase().includes(searchTerm.toLowerCase());
            let matchesCategory = true;
            if (selectedCategory === 'Favoritos') {
                matchesCategory = favorites.includes(food.name);
            } else if (selectedCategory !== 'Todos') {
                matchesCategory = food.category === selectedCategory;
            }
            return matchesSearch && matchesCategory;
        });
    }, [foods, searchTerm, selectedCategory, favorites]);



    return (
        <>
            <Header title="Base de Alimentos" showBack={true} />
            <main className="page" style={{ paddingBottom: '90px' }}>
                <div style={{
                    width: '100%',
                    height: '160px',
                    borderRadius: '24px',
                    overflow: 'hidden',
                    marginBottom: '1.5rem',
                    boxShadow: '0 8px 30px rgba(0,0,0,0.1)',
                    position: 'relative'
                }}>
                    <img
                        src="/nutrition_banner.png"
                        alt="Nutrition Banner"
                        style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                    />
                    <div style={{
                        position: 'absolute',
                        bottom: 0,
                        left: 0,
                        right: 0,
                        background: 'linear-gradient(transparent, rgba(0,0,0,0.6))',
                        padding: '1.5rem',
                        color: '#fff'
                    }}>
                        <div style={{ fontSize: '1.2rem', fontWeight: 900, textShadow: '0 2px 4px rgba(0,0,0,0.3)' }}>Guía Nutricional</div>
                        <div style={{ fontSize: '0.8rem', opacity: 0.9 }}>Consulta rápida de raciones de HC</div>
                    </div>
                </div>

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
                                    border: selectedCategory === cat ? 'none' : '1px solid #f1f5f9',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '8px'
                                }}
                            >
                                <span style={{ fontSize: '1.1rem' }}>{categoryIcons[cat] || '🍲'}</span>
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

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.2rem' }}>
                        {filteredFoods.length > 0 ? (
                            filteredFoods.map((food, idx) => {
                                const rating = getGIRating(food.ig);
                                const grams = portions[food.name] || '';
                                const rations = raciones_calculadas(food, grams);
                                const isFav = favorites.includes(food.name);

                                return (
                                    <div key={idx} style={{
                                        background: '#fff',
                                        padding: '1.2rem',
                                        borderRadius: '24px',
                                        display: 'flex',
                                        flexDirection: 'column',
                                        gap: '1rem',
                                        boxShadow: '0 4px 6px -1px rgba(0,0,0,0.02), 0 2px 4px -1px rgba(0,0,0,0.06)',
                                        border: '1px solid #f1f5f9',
                                        position: 'relative',
                                        overflow: 'hidden'
                                    }}>
                                        <div style={{ position: 'absolute', top: 0, left: 0, bottom: 0, width: '4px', backgroundColor: rating.color }}></div>

                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                            <div style={{ display: 'flex', gap: '12px', flex: 1 }}>
                                                <div style={{
                                                    fontSize: '1.8rem',
                                                    background: '#f8fafc',
                                                    width: '50px',
                                                    height: '50px',
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    justifyContent: 'center',
                                                    borderRadius: '14px',
                                                    border: '1px solid #f1f5f9'
                                                }}>
                                                    {categoryIcons[food.category] || '🍲'}
                                                </div>
                                                <div style={{ flex: 1 }}>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                        <div style={{ fontWeight: 800, color: '#1e293b', fontSize: '1.1rem' }}>{food.name}</div>
                                                        <button
                                                            onClick={() => toggleFavorite(food)}
                                                            title="Guardar en Mis Platos"
                                                            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1.3rem', padding: 0 }}
                                                        >
                                                            {isFav ? '⭐' : '☆'}
                                                        </button>
                                                    </div>
                                                    <div style={{ fontSize: '0.75rem', color: '#64748b', fontWeight: 600, marginTop: '2px' }}>
                                                        {food.category}
                                                    </div>
                                                </div>
                                            </div>
                                            <div style={{
                                                fontSize: '0.65rem',
                                                fontWeight: 900,
                                                textTransform: 'uppercase',
                                                padding: '4px 10px',
                                                borderRadius: '8px',
                                                backgroundColor: rating.bg,
                                                color: rating.color,
                                                letterSpacing: '0.05em'
                                            }}>
                                                IG {rating.label}
                                            </div>
                                        </div>

                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.8rem', background: '#f8fafc', borderRadius: '16px', padding: '1.2rem', border: '1px solid #f1f5f9' }}>
                                            <div style={{ display: 'flex', gap: '2rem' }}>
                                                <div style={{ flex: 1 }}>
                                                    <div style={{ fontSize: '0.65rem', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 800, marginBottom: '6px' }}>HC / 100g</div>
                                                    <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#1e293b' }}>
                                                        {food.ch_per_100g} <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#64748b' }}>g</span>
                                                    </div>
                                                </div>
                                                <div style={{ flex: 2, borderLeft: '1px solid #e2e8f0', paddingLeft: '2rem' }}>
                                                    <div style={{ fontSize: '0.65rem', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 800, marginBottom: '6px' }}>Medida Habitual</div>
                                                    <div style={{ fontSize: '0.9rem', fontWeight: 700, color: '#475569', lineHeight: '1.3' }}>
                                                        {food.measure || 'Sin especificar'}
                                                    </div>
                                                </div>
                                            </div>

                                            {/* CALCULATOR INTERFACE */}
                                            <div style={{
                                                display: 'flex',
                                                alignItems: 'flex-end',
                                                gap: '12px',
                                                borderTop: '1px solid #e2e8f0',
                                                paddingTop: '1rem',
                                                marginTop: '0.4rem'
                                            }}>
                                                <div style={{ flex: 1 }}>
                                                    <label style={{ fontSize: '0.65rem', color: '#64748b', fontWeight: 800, marginBottom: '6px', display: 'block' }}>GRAMOS</label>
                                                    <input
                                                        type="number"
                                                        value={grams}
                                                        onChange={(e) => setPortions(prev => ({ ...prev, [food.name]: e.target.value }))}
                                                        placeholder="0"
                                                        style={{
                                                            width: '100%',
                                                            padding: '0.6rem',
                                                            borderRadius: '10px',
                                                            border: '2px solid #e2e8f0',
                                                            fontSize: '1.1rem',
                                                            fontWeight: 800,
                                                            textAlign: 'center',
                                                            outline: 'none',
                                                            background: '#fff'
                                                        }}
                                                    />
                                                </div>
                                                <div style={{ flex: 1, textAlign: 'center', paddingBottom: '0.4rem' }}>
                                                    <div style={{ fontSize: '0.65rem', color: '#64748b', fontWeight: 800, marginBottom: '6px' }}>RACIONES</div>
                                                    <div style={{ fontSize: '1.4rem', fontWeight: 900, color: '#3b82f6', lineHeight: 1 }}>
                                                        {rations}
                                                    </div>
                                                </div>
                                                <div style={{ flex: 1.2 }}>
                                                    <Button
                                                        onClick={() => handleAddToCart(food, grams)}
                                                        className="btn-primary"
                                                        style={{
                                                            width: '100%',
                                                            padding: '0.7rem 0',
                                                            fontSize: '0.85rem',
                                                            borderRadius: '12px',
                                                            boxShadow: '0 4px 10px rgba(59, 130, 246, 0.2)',
                                                            display: 'flex',
                                                            alignItems: 'center',
                                                            justifyContent: 'center',
                                                            gap: '6px'
                                                        }}
                                                    >
                                                        <span>Añadir</span>
                                                        <span style={{ fontSize: '1.1rem' }}>+</span>
                                                    </Button>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                );
                            })
                        ) : (
                            <div style={{ textAlign: 'center', padding: '4rem 2rem' }}>
                                <div style={{ fontSize: '4rem', marginBottom: '1.5rem' }}>🔍</div>
                                <h4 style={{ color: '#1e293b', marginBottom: '0.5rem', fontWeight: 800 }}>Sin resultados</h4>
                                <p style={{ color: '#64748b', fontSize: '0.9rem', lineHeight: '1.5', maxWidth: '280px', margin: '0 auto 1.5rem' }}>
                                    Prueba con palabras más generales o revisa si el alimento tiene 0 HC.
                                </p>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.8rem', alignItems: 'center' }}>
                                    <Button
                                        onClick={() => { setSearchTerm(''); setSelectedCategory('Todos'); }}
                                        style={{ width: '220px' }}
                                    >
                                        Limpiar búsqueda
                                    </Button>
                                    <Button
                                        variant="secondary"
                                        onClick={() => navigate('#/')}
                                        style={{ width: '220px' }}
                                    >
                                        Volver al Inicio
                                    </Button>
                                </div>
                            </div>
                        )}
                    </div>
                </section>
            </main>
            {cart.length > 0 && (
                <div style={{
                    position: 'fixed',
                    bottom: '80px',
                    left: '1rem',
                    right: '1rem',
                    background: '#1e293b',
                    borderRadius: '20px',
                    padding: '1rem 1.5rem',
                    boxShadow: '0 10px 25px rgba(0,0,0,0.3)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    zIndex: 100,
                    animation: 'slideUp 0.3s ease-out'
                }}>
                    <div
                        onClick={() => setIsCartOpen(!isCartOpen)}
                        style={{ display: 'flex', flexDirection: 'column', cursor: 'pointer' }}
                    >
                        <div style={{ color: '#94a3b8', fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase' }}>
                            {cart.length} ITEMS
                        </div>
                        <div style={{ color: '#fff', fontSize: '1.3rem', fontWeight: 800 }}>
                            {cart.reduce((sum, item) => sum + item.carbs, 0).toFixed(1)}g <span style={{ fontSize: '0.9rem', color: '#64748b' }}>HC</span>
                        </div>
                    </div>

                    <Button
                        onClick={handleCheckout}
                        style={{
                            background: '#3b82f6',
                            color: '#fff',
                            borderRadius: '14px',
                            padding: '0.8rem 1.5rem',
                            fontSize: '0.9rem',
                            fontWeight: 700,
                            boxShadow: '0 4px 12px rgba(59, 130, 246, 0.4)',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px'
                        }}
                    >
                        Calcular Bolo
                        <span>→</span>
                    </Button>

                    {isCartOpen && (
                        <div style={{
                            position: 'absolute',
                            bottom: '100%',
                            left: 0,
                            right: 0,
                            marginBottom: '10px',
                            background: '#fff',
                            borderRadius: '20px',
                            padding: '1rem',
                            boxShadow: '0 10px 40px rgba(0,0,0,0.2)',
                            maxHeight: '300px',
                            overflowY: 'auto'
                        }}>
                            <h4 style={{ margin: '0 0 1rem', fontSize: '1rem', fontWeight: 800, color: '#1e293b' }}>Tu Plato</h4>
                            {cart.map((item) => (
                                <div key={item.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.8rem', borderBottom: '1px solid #f1f5f9', paddingBottom: '0.8rem' }}>
                                    <div>
                                        <div style={{ fontWeight: 700, fontSize: '0.9rem', color: '#334155' }}>{item.name}</div>
                                        <div style={{ fontSize: '0.75rem', color: '#64748b' }}>{item.amount}g • {item.carbs}g HC</div>
                                    </div>
                                    <button
                                        onClick={(e) => { e.stopPropagation(); removeFromCart(item.id); }}
                                        style={{ color: '#ef4444', background: '#fee2e2', border: 'none', borderRadius: '8px', width: '28px', height: '28px', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}
                                    >
                                        ✕
                                    </button>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}

            <BottomNav activeTab="home" />

            {/* Inline Styles for Animation */}
            <style>{`
                @keyframes slideUp {
                    from { transform: translateY(20px); opacity: 0; }
                    to { transform: translateY(0); opacity: 1; }
                }
            `}</style>
        </>
    );
}

function raciones_calculadas(food, grams) {
    if (!grams || isNaN(parseFloat(grams))) return '0';
    const val = (food.ch_per_100g * parseFloat(grams)) / 1000;
    return val % 1 === 0 ? val : val.toFixed(1);
}

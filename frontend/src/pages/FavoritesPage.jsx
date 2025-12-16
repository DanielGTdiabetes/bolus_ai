import React, { useState, useEffect } from 'react';
import { Card, Button, Input } from '../components/ui/Atoms';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';

// Mock Favorites Store (We'll move this to store.js later or use localStorage directly here)
const FAV_KEY = "bolusai_favorites";

function getFavorites() {
    try {
        return JSON.parse(localStorage.getItem(FAV_KEY) || "[]");
    } catch { return []; }
}

function saveFavorites(favs) {
    localStorage.setItem(FAV_KEY, JSON.stringify(favs));
}

export default function FavoritesPage({ navigate }) {
    const [favorites, setFavorites] = useState([]);
    const [isAdding, setIsAdding] = useState(false);
    const [newFav, setNewFav] = useState({ name: "", carbs: "" });

    useEffect(() => {
        setFavorites(getFavorites());
    }, []);

    const handleAdd = () => {
        if (!newFav.name || !newFav.carbs) return;
        const updated = [...favorites, { ...newFav, id: Date.now() }];
        saveFavorites(updated);
        setFavorites(updated);
        setNewFav({ name: "", carbs: "" });
        setIsAdding(false);
    };

    const handleDelete = (id) => {
        const updated = favorites.filter(f => f.id !== id);
        saveFavorites(updated);
        setFavorites(updated);
    };

    const handleLoad = (fav) => {
        // Direct injection into legacy store logic!
        // We know store.js uses 'tempCarbs' for passing data to Bolus view.
        // But we are in React isolation. We need to interact with the "Global World".

        // Option 1: Dispatch Event
        // Option 2: Direct manipulation of window if available, or imports.
        // We'll use the 'navigate' prop passed from the bridge which wraps the router.navigate

        // Let's assume we can trigger the legacy logic via global state or url params.
        // For now, simpler: Set localStorage or dispatch event.

        // Hacky Bridge: Import state from store.js? 
        // Better: The bridge passes a context.

        // For this demo, let's just alert
        // alert(`Cargando ${fav.carbs}g de ${fav.name}`);

        // Real logic:
        import('../modules/core/store.js').then(({ state }) => {
            state.tempCarbs = parseFloat(fav.carbs);
            state.tempReason = `Fav: ${fav.name}`;
            window.location.hash = "#/bolus"; // Legacy Router Override
        });
    };

    return (
        <>
            <Header title="Favoritos" showBack={true} />
            <div className="page fade-in" style={{ paddingBottom: '80px' }}>
                <h2 style={{ marginBottom: '1rem', marginTop: 0 }}>⭐ Comidas Favoritas</h2>

                <div style={{ marginBottom: '1.5rem' }}>
                    {favorites.length === 0 ? (
                        <div className="text-muted text-center" style={{ padding: '2rem' }}>
                            No tienes favoritos guardados.
                        </div>
                    ) : (
                        <div className="stack">
                            {favorites.map(fav => (
                                <Card key={fav.id} className="summary-row" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '1rem' }}>
                                    <div>
                                        <div style={{ fontWeight: 700, fontSize: '1.1rem' }}>{fav.name}</div>
                                        <div className="text-teal">{fav.carbs}g Carbs</div>
                                    </div>
                                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                                        <Button variant="secondary" onClick={() => handleLoad(fav)} style={{ padding: '0.5rem 1rem' }}>
                                            Cargar
                                        </Button>
                                        <button onClick={() => handleDelete(fav.id)} style={{ border: 'none', background: 'none', color: '#ef4444', fontSize: '1.2rem' }}>
                                            🗑️
                                        </button>
                                    </div>
                                </Card>
                            ))}
                        </div>
                    )}
                </div>

                {isAdding ? (
                    <Card title="Nueva Comida">
                        <div className="stack">
                            <Input
                                label="Nombre"
                                placeholder="Ej: Tostada desayuno"
                                value={newFav.name}
                                onChange={e => setNewFav({ ...newFav, name: e.target.value })}
                            />
                            <Input
                                label="Carbohidratos (g)"
                                type="number"
                                placeholder="0"
                                value={newFav.carbs}
                                onChange={e => setNewFav({ ...newFav, carbs: e.target.value })}
                            />
                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                                <Button onClick={handleAdd}>Guardar</Button>
                                <Button variant="ghost" onClick={() => setIsAdding(false)}>Cancelar</Button>
                            </div>
                        </div>
                    </Card>
                ) : (
                    <Button onClick={() => setIsAdding(true)}>+ Añadir Favorito</Button>
                )}

                <div style={{ marginTop: '2rem', textAlign: 'center' }}>
                    {/* Back Link redundant if Header has back */}
                </div>
            </div>
            <BottomNav />
        </>
    );
}

// Simple Fade In animation for React pages
const style = document.createElement('style');
style.innerHTML = `
  .fade-in { animation: fadeIn 0.3s ease-out; }
`;
document.head.appendChild(style);

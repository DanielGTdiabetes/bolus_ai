import React, { useState, useEffect } from 'react';
import { Card, Button, Input } from '../components/ui/Atoms';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { getFavorites, addFavorite, deleteFavorite } from '../lib/api';

export default function FavoritesPage({ navigate }) {
    const [favorites, setFavorites] = useState([]);
    const [searchQuery, setSearchQuery] = useState("");
    const [isAdding, setIsAdding] = useState(false);
    const [newFav, setNewFav] = useState({ name: "", carbs: "" });
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const loadData = async () => {
        setLoading(true);
        try {
            const data = await getFavorites();
            data.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0)); // Newer first if needed, or by name
            setFavorites(data);
        } catch (e) {
            setError("Error cargando favoritos");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadData();
    }, []);

    const handleAdd = async () => {
        if (!newFav.name || !newFav.carbs) return;
        setLoading(true);
        try {
            await addFavorite(newFav.name, parseFloat(newFav.carbs));
            await loadData();
            setNewFav({ name: "", carbs: "" });
            setIsAdding(false);
        } catch (e) {
            alert(e.message);
            setLoading(false);
        }
    };

    const handleDelete = async (id) => {
        if (!confirm("¿Borrar favorito?")) return;
        try {
            await deleteFavorite(id);
            setFavorites(prev => prev.filter(f => f.id !== id));
        } catch (e) {
            alert(e.message);
        }
    };

    const handleLoad = (fav) => {
        import('../modules/core/store.js').then(({ state }) => {
            state.tempCarbs = parseFloat(fav.carbs);
            state.tempReason = `Fav: ${fav.name}`;
            window.location.hash = "#/bolus";
        });
    };



    const normalize = (str) => str.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    const filteredFavorites = favorites.filter(f => normalize(f.name).includes(normalize(searchQuery)));

    return (
        <>
            <Header title="Favoritos" showBack={true} />
            <div className="page fade-in" style={{ paddingBottom: '80px' }}>
                <h2 style={{ marginBottom: '1rem', marginTop: 0 }}>⭐ Comidas Favoritas</h2>

                {error && <div className="error">{error}</div>}

                <div style={{ marginBottom: '1rem' }}>
                    <Input
                        placeholder="🔍 Buscar en favoritos..."
                        value={searchQuery}
                        onChange={e => setSearchQuery(e.target.value)}
                        style={{ padding: '0.8rem', fontSize: '1rem', borderRadius: '12px', border: '1px solid #cbd5e1' }}
                    />
                </div>

                <div style={{ marginBottom: '1.5rem' }}>
                    {loading && favorites.length === 0 ? (
                        <div className="spinner">Cargando...</div>
                    ) : filteredFavorites.length === 0 ? (
                        <div className="text-muted text-center" style={{ padding: '2rem' }}>
                            {searchQuery ? "No se encontraron coincidencias." : "No tienes favoritos guardados."}
                        </div>
                    ) : (
                        <div className="stack">
                            {filteredFavorites.map(fav => (
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
                                <Button onClick={handleAdd} disabled={loading}>Guardar</Button>
                                <Button variant="ghost" onClick={() => setIsAdding(false)}>Cancelar</Button>
                            </div>
                        </div>
                    </Card>
                ) : (
                    <Button onClick={() => setIsAdding(true)}>+ Añadir Favorito</Button>
                )}
            </div>
            <BottomNav />
        </>
    );
}

const style = document.createElement('style');
style.innerHTML = `
  .fade-in { animation: fadeIn 0.3s ease-out; }
`;
document.head.appendChild(style);

import React, { useState, useEffect } from 'react';
import { Card, Button, Input } from '../components/ui/Atoms';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { getFavorites, addFavorite, deleteFavorite, updateFavorite } from '../lib/api';

export default function FavoritesPage({ navigate }) {
    const [favorites, setFavorites] = useState([]);
    const [searchQuery, setSearchQuery] = useState("");
    const [isAdding, setIsAdding] = useState(false);
    const [newFav, setNewFav] = useState({ name: "", carbs: "", fat: "", protein: "", fiber: "", notes: "" });
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    // Edit State
    const [editingId, setEditingId] = useState(null);
    const [editForm, setEditForm] = useState({ name: "", carbs: "", fat: "", protein: "", fiber: "", notes: "" });

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
            await addFavorite({
                name: newFav.name,
                carbs: parseFloat(newFav.carbs),
                fat: parseFloat(newFav.fat) || 0,
                protein: parseFloat(newFav.protein) || 0,
                fat: parseFloat(newFav.fat) || 0,
                protein: parseFloat(newFav.protein) || 0,
                fiber: parseFloat(newFav.fiber) || 0,
                notes: newFav.notes
            });
            await loadData();
            setNewFav({ name: "", carbs: "", fat: "", protein: "", fiber: "", notes: "" });
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

    const startEdit = (fav) => {
        setEditingId(fav.id);
        setEditForm({
            name: fav.name,
            carbs: fav.carbs,
            fat: fav.fat || "",
            protein: fav.protein || "",
            protein: fav.protein || "",
            fiber: fav.fiber || "",
            notes: fav.notes || ""
        });
    };

    const cancelEdit = () => {
        setEditingId(null);
        setEditForm({ name: "", carbs: "", fat: "", protein: "", fiber: "", notes: "" });
    };

    const handleUpdate = async () => {
        if (!editForm.name || !editForm.carbs) return alert("Rellena los campos");
        setLoading(true);
        try {
            const updated = await updateFavorite(editingId, {
                name: editForm.name,
                carbs: parseFloat(editForm.carbs),
                fat: parseFloat(editForm.fat) || 0,
                protein: parseFloat(editForm.protein) || 0,
                fat: parseFloat(editForm.fat) || 0,
                protein: parseFloat(editForm.protein) || 0,
                fiber: parseFloat(editForm.fiber) || 0,
                notes: editForm.notes
            });
            // Update list locally
            setFavorites(prev => prev.map(f => f.id === editingId ? updated : f));
            setEditingId(null);
        } catch (e) {
            alert(e.message);
        } finally {
            setLoading(false);
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
            <Header title="Mis Platos" showBack={true} />
            <div className="page fade-in" style={{ paddingBottom: '80px' }}>
                <h2 style={{ marginBottom: '1rem', marginTop: 0 }}>📚 Mis Platos Guardados</h2>

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
                                <React.Fragment key={fav.id}>
                                    {editingId === fav.id ? (
                                        <Card className="summary-row" style={{ padding: '1rem', background: '#f0f9ff', border: '1px solid #bae6fd' }}>
                                            <div className="stack">
                                                <Input
                                                    label="Nombre"
                                                    value={editForm.name}
                                                    onChange={e => setEditForm({ ...editForm, name: e.target.value })}
                                                />
                                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: '0.5rem' }}>
                                                    <Input
                                                        label="Carbos"
                                                        type="number"
                                                        value={editForm.carbs}
                                                        onChange={e => setEditForm({ ...editForm, carbs: e.target.value })}
                                                    />
                                                    <Input
                                                        label="Grasas"
                                                        type="number"
                                                        value={editForm.fat}
                                                        onChange={e => setEditForm({ ...editForm, fat: e.target.value })}
                                                    />
                                                    <Input
                                                        label="Prot"
                                                        type="number"
                                                        value={editForm.protein}
                                                        onChange={e => setEditForm({ ...editForm, protein: e.target.value })}
                                                    />
                                                    <Input
                                                        label="Fibra"
                                                        type="number"
                                                        value={editForm.fiber}
                                                        onChange={e => setEditForm({ ...editForm, fiber: e.target.value })}
                                                    />
                                                </div>
                                                <Input
                                                    label="Notas"
                                                    value={editForm.notes}
                                                    onChange={e => setEditForm({ ...editForm, notes: e.target.value })}
                                                />
                                                <div style={{ display: 'flex', gap: '0.5rem' }}>
                                                    <Button onClick={handleUpdate} size="sm">Guardar</Button>
                                                    <Button variant="ghost" onClick={cancelEdit} size="sm">Cancelar</Button>
                                                </div>
                                            </div>
                                        </Card>
                                    ) : (
                                        <Card className="summary-row" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '1rem' }}>
                                            <div>
                                                <div style={{ fontWeight: 700, fontSize: '1.1rem' }}>{fav.name}</div>
                                                <div className="text-teal">
                                                    {fav.carbs}g HC
                                                    {(fav.fiber > 0) && <span style={{ fontSize: '0.8em', color: '#64748b' }}> ({fav.fiber}g Fibra)</span>}
                                                </div>
                                            </div>
                                            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                                <Button variant="secondary" onClick={() => handleLoad(fav)} style={{ padding: '0.5rem 1rem' }}>
                                                    Cargar
                                                </Button>
                                                <button onClick={() => startEdit(fav)} style={{ border: 'none', background: 'none', cursor: 'pointer', fontSize: '1.2rem' }} title="Editar">
                                                    ✏️
                                                </button>
                                                <button onClick={() => handleDelete(fav.id)} style={{ border: 'none', background: 'none', color: '#ef4444', cursor: 'pointer', fontSize: '1.2rem' }} title="Borrar">
                                                    🗑️
                                                </button>
                                            </div>
                                        </Card>
                                    )}
                                </React.Fragment>
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
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: '0.5rem' }}>
                                <Input
                                    label="Carbos"
                                    type="number"
                                    placeholder="0"
                                    value={newFav.carbs}
                                    onChange={e => setNewFav({ ...newFav, carbs: e.target.value })}
                                />
                                <Input
                                    label="Grasas"
                                    type="number"
                                    placeholder="0"
                                    value={newFav.fat}
                                    onChange={e => setNewFav({ ...newFav, fat: e.target.value })}
                                />
                                <Input
                                    label="Prot"
                                    type="number"
                                    placeholder="0"
                                    value={newFav.protein}
                                    onChange={e => setNewFav({ ...newFav, protein: e.target.value })}
                                />
                                <Input
                                    label="Fibra"
                                    type="number"
                                    placeholder="0"
                                    value={newFav.fiber}
                                    onChange={e => setNewFav({ ...newFav, fiber: e.target.value })}
                                />
                            </div>
                            <Input
                                label="Notas"
                                placeholder="Opcional"
                                value={newFav.notes}
                                onChange={e => setNewFav({ ...newFav, notes: e.target.value })}
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

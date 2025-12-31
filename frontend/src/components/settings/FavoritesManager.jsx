
import React, { useState, useEffect } from 'react';
import { Button, Input } from '../ui/Atoms';
import { getFavorites, saveFavorite, updateFavorite, deleteFavorite } from '../../lib/api';

export function FavoritesManager() {
    const [favorites, setFavorites] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [editing, setEditing] = useState(null); // null or favorite object

    // Form state
    const [form, setForm] = useState({ name: '', carbs: '', fat: '', protein: '', notes: '' });

    useEffect(() => {
        fetchFavorites();
    }, []);

    const fetchFavorites = async () => {
        setLoading(true);
        setError(null);
        try {
            const data = await getFavorites();
            setFavorites(data || []);
        } catch (e) {
            console.error(e);
            setError("Error cargando favoritos: " + e.message);
        } finally {
            setLoading(false);
        }
    };

    const handleSave = async () => {
        if (!form.name) return alert("El nombre es obligatorio");

        // Parse numbers safely
        const payload = {
            name: form.name,
            carbs: parseFloat(form.carbs) || 0,
            fat: parseFloat(form.fat) || 0,
            protein: parseFloat(form.protein) || 0,
            notes: form.notes || null
        };

        try {
            if (editing) {
                await updateFavorite(editing.id, payload);
            } else {
                await saveFavorite(payload);
            }

            // Reset UI
            setEditing(null);
            setForm({ name: '', carbs: '', fat: '', protein: '', notes: '' });
            fetchFavorites(); // Refresh list
        } catch (e) {
            alert("Error al guardar: " + e.message);
        }
    };

    const handleDelete = async (id) => {
        if (!window.confirm("¿Seguro que quieres borrar esta comida?")) return;
        try {
            await deleteFavorite(id);
            fetchFavorites();
        } catch (e) {
            alert("Error al borrar: " + e.message);
        }
    };

    const startEdit = (fav) => {
        setEditing(fav);
        setForm({
            name: fav.name,
            carbs: fav.carbs,
            fat: fav.fat || '',
            protein: fav.protein || '',
            notes: fav.notes || ''
        });
        // Scroll to form to ensure visibility
        document.getElementById('fav-form')?.scrollIntoView({ behavior: 'smooth' });
    };

    const cancelEdit = () => {
        setEditing(null);
        setForm({ name: '', carbs: '', fat: '', protein: '', notes: '' });
    };

    if (loading && favorites.length === 0) return <div className="p-4 text-center">Cargando librería...</div>;

    return (
        <div className="favorites-manager stack">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h3 style={{ marginTop: 0 }}>Librería de Comidas</h3>
                <Button variant="ghost" onClick={fetchFavorites}>🔄</Button>
            </div>

            {error && <div className="error-box" style={{ color: 'red', padding: '0.5rem' }}>{error}</div>}

            {/* Formulario */}
            <div id="fav-form" style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                <h4 style={{ margin: '0 0 1rem 0', color: '#334155' }}>
                    {editing ? `✏️ Editando: ${editing.name}` : '➕ Añadir Nueva Comida'}
                </h4>

                <div className="stack">
                    <Input
                        label="Nombre del Plato"
                        value={form.name}
                        onChange={e => setForm({ ...form, name: e.target.value })}
                        placeholder="Ej: Pizza Casera"
                    />

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.5rem' }}>
                        <Input
                            label="Carbos (g)"
                            type="number"
                            value={form.carbs}
                            onChange={e => setForm({ ...form, carbs: e.target.value })}
                        />
                        <Input
                            label="Grasas (g)"
                            type="number"
                            value={form.fat}
                            onChange={e => setForm({ ...form, fat: e.target.value })}
                        />
                        <Input
                            label="Proteínas (g)"
                            type="number"
                            value={form.protein}
                            onChange={e => setForm({ ...form, protein: e.target.value })}
                        />
                    </div>

                    <Input
                        label="Notas / Restaurante"
                        value={form.notes}
                        onChange={e => setForm({ ...form, notes: e.target.value })}
                        placeholder="Opcional: Info extra"
                    />

                    <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
                        <Button onClick={handleSave} style={{ flex: 1 }}>
                            {editing ? 'Guardar Cambios' : 'Añadir a Librería'}
                        </Button>
                        {editing && (
                            <Button variant="secondary" onClick={cancelEdit}>
                                Cancelar
                            </Button>
                        )}
                    </div>
                </div>
            </div>

            {/* Lista de Favoritos */}
            <div className="fav-list stack" style={{ marginTop: '1rem' }}>
                {favorites.length === 0 && !loading && (
                    <div className="text-muted text-center p-4">No hay comidas guardadas aún.</div>
                )}

                {favorites.map(f => (
                    <div key={f.id} style={{
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                        padding: '0.8rem', background: 'white', borderRadius: '8px', border: '1px solid #e2e8f0',
                        boxShadow: '0 1px 2px rgba(0,0,0,0.05)'
                    }}>
                        <div style={{ flex: 1 }}>
                            <div style={{ fontWeight: 600, fontSize: '1rem', color: '#1e293b' }}>{f.name}</div>
                            <div style={{ fontSize: '0.85rem', color: '#64748b', marginTop: '4px' }}>
                                <span style={{ color: '#0369a1', fontWeight: 600, background: '#e0f2fe', padding: '2px 6px', borderRadius: '4px' }}>
                                    {f.carbs}g HC
                                </span>
                                {(f.fat > 0 || f.protein > 0) && (
                                    <span style={{ marginLeft: '8px' }}>
                                        Fat: {f.fat}g • Prot: {f.protein}g
                                    </span>
                                )}
                            </div>
                            {f.notes && (
                                <div style={{ fontSize: '0.75rem', color: '#94a3b8', fontStyle: 'italic', marginTop: '4px' }}>
                                    📝 {f.notes}
                                </div>
                            )}
                        </div>

                        <div style={{ display: 'flex', gap: '0.5rem' }}>
                            <Button variant="ghost" onClick={() => startEdit(f)} style={{ padding: '0.5rem', fontSize: '1.1rem' }} title="Editar">
                                ✏️
                            </Button>
                            <Button variant="ghost" onClick={() => handleDelete(f.id)} style={{ padding: '0.5rem', color: '#ef4444', fontSize: '1.1rem' }} title="Borrar">
                                🗑️
                            </Button>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}

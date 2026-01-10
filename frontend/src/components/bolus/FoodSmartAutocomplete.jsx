
import React, { useState, useEffect } from 'react';

export function FoodSmartAutocomplete({ value, onChange, onSelect, favorites = [] }) {
    const [suggestions, setSuggestions] = useState([]);
    const [bestMatch, setBestMatch] = useState('');

    const acceptMatch = () => {
        if (!bestMatch) return;
        const item = favorites.find(f => f.name === bestMatch);
        if (item) {
            onSelect(item);
            setBestMatch('');
            setSuggestions([]);
        }
    };

    // Helper for accent-insensitive comparison
    const normalize = (str) => str.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

    // Suggest based on input
    useEffect(() => {
        if (!value || value.length < 1) {
            setSuggestions([]);
            setBestMatch('');
            return;
        }

        const normVal = normalize(value.trim());

        // 1. Ghost Match: Must start with input (accent-insensitive)
        const prefixMatch = favorites.find(f => normalize(f.name).startsWith(normVal));
        if (prefixMatch) {
            setBestMatch(prefixMatch.name);
        } else {
            setBestMatch('');
        }

        // 2. Dropdown Match: Contains input (accent-insensitive)
        const matches = favorites.filter(f => normalize(f.name).includes(normVal));
        setSuggestions(matches.slice(0, 5));
    }, [value, favorites]);

    const handleKeyDown = (e) => {
        if ((e.key === 'Enter' || e.key === 'Tab') && bestMatch) {
            e.preventDefault();
            acceptMatch();
        }
    };

    return (
        <div style={{ position: 'relative' }}>
            <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                {/* Ghost Input Layer */}
                <input
                    type="text"
                    readOnly
                    value={bestMatch}
                    style={{
                        position: 'absolute', top: 0, left: 0, width: '100%', height: '100%',
                        color: '#94a3b8',
                        background: 'transparent',
                        border: '1px solid transparent',
                        borderRadius: '8px',
                        padding: '0.5rem',
                        fontSize: '1rem',
                        pointerEvents: 'none',
                        zIndex: 1
                    }}
                    tabIndex={-1}
                />

                {/* Real Input Layer */}
                <input
                    type="text"
                    placeholder={bestMatch ? "" : "Ej: Pizza, Manzana..."}
                    value={value}
                    onChange={e => onChange(e.target.value)}
                    onKeyDown={handleKeyDown}
                    style={{
                        width: '100%',
                        position: 'relative',
                        zIndex: 2,
                        background: 'transparent',
                        border: '1px solid #cbd5e1',
                        borderRadius: '8px',
                        padding: '0.5rem',
                        fontSize: '1rem',
                        color: 'var(--text)'
                    }}
                    autoComplete="off"
                />

                {/* Mobile 'Use' Button */}
                {bestMatch && bestMatch.toLowerCase() !== value.toLowerCase() && (
                    <div
                        onClick={acceptMatch}
                        style={{
                            position: 'absolute',
                            right: '10px',
                            zIndex: 3,
                            color: 'var(--primary)',
                            cursor: 'pointer',
                            fontWeight: 'bold',
                            background: '#eff6ff',
                            padding: '2px 8px',
                            borderRadius: '4px',
                            border: '1px solid #bfdbfe',
                            fontSize: '0.8rem'
                        }}
                    >
                        ↲ Usar
                    </div>
                )}
            </div>

            {/* Dropdown Suggestions */}
            {suggestions.length > 0 && (
                <div style={{
                    position: 'absolute', top: '105%', left: 0, right: 0,
                    background: '#fff', border: '1px solid #cbd5e1',
                    borderRadius: '8px', zIndex: 10, boxShadow: '0 4px 6px rgba(0,0,0,0.1)'
                }}>
                    {suggestions.map(s => {
                        const matchIndex = s.name.toLowerCase().indexOf(value.toLowerCase());
                        const before = matchIndex >= 0 ? s.name.slice(0, matchIndex) : s.name;
                        const match = matchIndex >= 0 ? s.name.slice(matchIndex, matchIndex + value.length) : "";
                        const after = matchIndex >= 0 ? s.name.slice(matchIndex + value.length) : "";

                        return (
                            <div
                                key={s.id}
                                onClick={() => {
                                    onSelect(s);
                                    setSuggestions([]);
                                    setBestMatch('');
                                }}
                                style={{
                                    padding: '0.8rem', borderBottom: '1px solid #f1f5f9',
                                    cursor: 'pointer', display: 'flex', justifyContent: 'space-between',
                                    background: bestMatch === s.name ? '#f0f9ff' : 'transparent'
                                }}
                            >
                                <span>{before}<strong>{match}</strong>{after}</span>
                                <span style={{ fontWeight: 700, color: 'var(--primary)' }}>{s.carbs}g</span>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

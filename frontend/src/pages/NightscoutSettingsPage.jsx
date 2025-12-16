import React, { useState, useEffect } from 'react';
import { getSecretStatus, putSecret, deleteSecret } from '../lib/api';


export default function NightscoutSettingsPage() {
    const [url, setUrl] = useState('');
    const [token, setToken] = useState('');
    const [enabled, setEnabled] = useState(false);
    const [hasSecret, setHasSecret] = useState(false);
    const [message, setMessage] = useState('');

    useEffect(() => {
        async function fetchStatus() {
            try {
                const data = await getSecretStatus();
                setUrl(data.url || '');
                setEnabled(data.enabled);
                setHasSecret(data.has_secret);
            } catch (e) {
                console.error('Failed to load Nightscout secret status', e);
            }
        }
        fetchStatus();
    }, []);

    const handleSave = async (e) => {
        e.preventDefault();
        try {
            await putSecret({ url, api_secret: token, enabled });
            setMessage('Nightscout credentials saved');
            setHasSecret(true);
        } catch (err) {
            setMessage('Error saving credentials');
        }
    };

    const handleDelete = async () => {
        try {
            await deleteSecret();
            setUrl('');
            setToken('');
            setEnabled(false);
            setHasSecret(false);
            setMessage('Credentials removed');
        } catch (err) {
            setMessage('Error removing credentials');
        }
    };

    return (
        <div className="nightscout-settings container mx-auto p-4">
            <h1 className="text-2xl font-bold mb-4">Nightscout Configuration</h1>
            {message && <p className="mb-2 text-green-600">{message}</p>}
            <form onSubmit={handleSave} className="space-y-4">
                <div>
                    <label className="block font-medium">Nightscout URL</label>
                    <input
                        type="text"
                        value={url}
                        onChange={(e) => setUrl(e.target.value)}
                        className="w-full border rounded p-2"
                        placeholder="https://my-nightscout.example.com"
                        required
                    />
                </div>
                <div>
                    <label className="block font-medium">API Secret (Token)</label>
                    <input
                        type="password"
                        value={token}
                        onChange={(e) => setToken(e.target.value)}
                        className="w-full border rounded p-2"
                        placeholder="Your Nightscout token"
                        required
                    />
                </div>
                <div className="flex items-center">
                    <input
                        type="checkbox"
                        checked={enabled}
                        onChange={(e) => setEnabled(e.target.checked)}
                        id="enabled"
                        className="mr-2"
                    />
                    <label htmlFor="enabled" className="font-medium">Enabled</label>
                </div>
                <button
                    type="submit"
                    className="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700"
                >
                    Save
                </button>
                {hasSecret && (
                    <button
                        type="button"
                        onClick={handleDelete}
                        className="bg-red-600 text-white px-4 py-2 rounded hover:bg-red-700"
                    >
                        Delete Credentials
                    </button>
                )}
            </form>
        </div>
    );
}

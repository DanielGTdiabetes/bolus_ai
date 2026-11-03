const FLASH = 'gemini-3.5-flash-lite';
const REASONING = 'gemini-3.8-flash';
const replacements = {
    'gemini-1.5-flash': FLASH,
    'gemini-2.0-flash': FLASH,
    'gemini-2.0-flash-exp': FLASH,
    'gemini-2.5-flash': FLASH,
    'gemini-3-flash-preview': FLASH,
    'gemini-1.5-pro': REASONING,
    'gemini-2.5-pro': REASONING,
    'gemini-3-pro-preview': REASONING,
};

export function migrateGeminiSettings(settings) {
    if (!settings?.vision || typeof settings.vision !== 'object' || Array.isArray(settings.vision)) return settings;
    const vision = { ...settings.vision };
    for (const key of ['gemini_model', 'gemini_transcribe_model']) {
        if (typeof vision[key] !== 'string') continue;
        const model = vision[key].trim().replace(/^models\//, '') || FLASH;
        vision[key] = replacements[model] || model;
    }
    return { ...settings, vision };
}

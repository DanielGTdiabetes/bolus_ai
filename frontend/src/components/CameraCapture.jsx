import React, { useRef } from 'react';
import { Button } from './ui/Atoms';

/**
 * Simple helper to trigger the native camera without extra steps.
 * Renders a hidden file input and a button that programmatically opens it.
 */
export function CameraCapture({ buttonLabel, onCapture, disabled = false, variant, style }) {
    const inputRef = useRef(null);

    const handleClick = () => {
        if (!disabled && inputRef.current) {
            inputRef.current.click();
        }
    };

    const handleChange = async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        if (onCapture) await onCapture(file);
        // Reset so the same file can be selected again if needed
        e.target.value = '';
    };

    return (
        <>
            <Button onClick={handleClick} disabled={disabled} variant={variant} style={style}>
                {buttonLabel}
            </Button>
            <input
                type="file"
                accept="image/*"
                capture="environment"
                hidden
                ref={inputRef}
                onChange={handleChange}
            />
        </>
    );
}


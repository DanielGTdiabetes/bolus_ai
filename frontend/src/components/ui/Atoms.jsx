import React from 'react';

export function Button({ children, onClick, variant = 'primary', className = '', ...props }) {
    const baseClass = "btn";
    // Mapping variants to existing CSS classes in style.css
    const variantClass = variant === 'primary' ? 'btn-primary'
        : variant === 'secondary' ? 'btn-secondary'
            : 'btn-ghost';

    return (
        <button
            className={`${variantClass} ${className}`}
            onClick={onClick}
            {...props}
        >
            {children}
        </button>
    );
}

export function Card({ children, className = '', title }) {
    return (
        <div className={`card ${className}`}>
            {title && <h3 style={{ marginTop: 0 }}>{title}</h3>}
            {children}
        </div>
    );
}

export function Input({ label, type = "text", value, onChange, placeholder, ...props }) {
    return (
        <div className="form-group">
            {label && <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 600 }}>{label}</label>}
            <input
                type={type}
                value={value}
                onChange={onChange}
                placeholder={placeholder}
                {...props}
            />
        </div>
    );
}
